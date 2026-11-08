import os
import re
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from swayctl_center import governor as g
from swayctl_center import schema
from swayctl_center.modules.priority import PriorityModule, settings_from


# the tests never touch the real swayctl-background.slice (and a name without a dash has no parent slice)
g.SLICE = "scctest.slice"


def tearDownModule():
    subprocess.run(["systemctl", "--user", "stop", g.SLICE], capture_output=True)


def proc(pid, ppid=1, comm="x", cmd="", nice=0, policy=os.SCHED_OTHER, kernel=False, start=1):
    return g.ProcInfo(pid, ppid, comm, cmd or comm, start, nice, policy, kernel)


def settings(rules=(), protect=("sway",), **kw):
    return g.Settings(g.compile_rules(rules), g.protect_pattern(protect), **kw)


MVN = {"match": r"classworlds", "field": "cmdline", "tier": "batch"}
LSP = {"match": r"^jdtls$", "field": "name", "tier": "background"}


class ClassifyTest(unittest.TestCase):
    def test_first_matching_rule_wins_and_unmatched_is_left_alone(self):
        s = settings([LSP, {"match": "jdt", "tier": "batch"}])
        self.assertEqual(g.classify(proc(1, comm="jdtls"), s.rules, s.protect), "background")
        self.assertIsNone(g.classify(proc(2, comm="firefox"), s.rules, s.protect))

    def test_cmdline_rules_look_at_the_command_line(self):
        s = settings([MVN])
        p = proc(1, comm="java", cmd="java -cp x org.codehaus.plexus.classworlds.launcher.Launcher")
        self.assertEqual(g.classify(p, s.rules, s.protect), "batch")
        self.assertIsNone(g.classify(proc(2, comm="java", cmd="java -jar app.jar"), s.rules, s.protect))

    def test_protected_kernel_and_realtime_are_never_touched(self):
        s = settings([{"match": ".", "tier": "batch"}], protect=("sway",))
        self.assertIsNone(g.classify(proc(1, comm="sway"), s.rules, s.protect))
        self.assertIsNone(g.classify(proc(2, comm="kworker", kernel=True), s.rules, s.protect))
        self.assertIsNone(g.classify(proc(3, comm="rt", policy=os.SCHED_RR), s.rules, s.protect))

    def test_disabled_and_broken_rules_are_skipped(self):
        rules = g.compile_rules([{"match": "a", "tier": "batch", "enabled": False},
                                 {"match": "(", "tier": "batch"}, {"match": "b", "tier": "batch"}])
        self.assertEqual([r.match.pattern for r in rules], ["b"])


class PlanTest(unittest.TestCase):
    def table(self, procs):
        return {p.pid: p for p in procs}

    def test_a_matched_process_hands_its_tier_to_its_children(self):
        procs = self.table([proc(10, comm="mvn-java", cmd="classworlds"), proc(11, 10, "javac"),
                            proc(12, 11, "cc1"), proc(13, 1, "zsh"), proc(14, 11, "sway")])
        out = g.plan(procs, settings([MVN]), None, False)
        self.assertEqual(set(out), {10, 11, 12})  # not the unrelated shell, not the protected child
        self.assertEqual(out[12].nice, 19)
        self.assertEqual(out[12].io_class, g.IO_IDLE)
        self.assertEqual(out[12].policy, os.SCHED_BATCH)

    def test_a_childs_own_rule_beats_the_parents_tier(self):
        procs = self.table([proc(10, cmd="classworlds"), proc(11, 10, "jdtls")])
        out = g.plan(procs, settings([MVN, LSP], background_nice=7), None, False)
        self.assertEqual(out[11].nice, 7)

    def test_focus_boost_raises_the_focused_app_and_its_children_only_when_it_helps(self):
        procs = self.table([proc(20, comm="chrome", nice=0), proc(21, 20, "renderer", nice=0),
                            proc(22, 20, "gpu", nice=-8), proc(23, 1, "other", nice=0)])
        out = g.plan(procs, settings(focus_nice=-4), 20, False)
        self.assertEqual(set(out), {20, 21})   # 22 already has more than -4; 23 isn't the focused app
        self.assertEqual(out[20].nice, -4)

    def test_focus_boost_never_overrides_a_rule_and_can_be_off(self):
        procs = self.table([proc(30, comm="jdtls")])
        out = g.plan(procs, settings([LSP]), 30, False)
        self.assertEqual(out[30].nice, 10)
        self.assertEqual(g.plan(self.table([proc(31, comm="a")]), settings(focus_boost=False), 31, False), {})

    def test_pressure_pushes_background_to_the_batch_values(self):
        procs = self.table([proc(40, comm="jdtls")])
        calm = g.plan(procs, settings([LSP]), None, False)[40]
        busy = g.plan(procs, settings([LSP]), None, True)[40]
        self.assertEqual((calm.nice, busy.nice), (10, 19))
        self.assertEqual(busy.io_class, g.IO_IDLE)

    def test_the_daemon_itself_is_skipped(self):
        procs = self.table([proc(os.getpid(), comm="python")])
        self.assertEqual(g.plan(procs, settings([{"match": ".", "tier": "batch"}], protect=()), None, False,
                                own_pid=os.getpid()), {})


class PressureTest(unittest.TestCase):
    def test_hysteresis(self):
        low, high = {"cpu": 10.0, "io": 0.0, "memory": 0.0}, {"cpu": 70.0, "io": 0.0, "memory": 0.0}
        mid = {"cpu": 45.0, "io": 0.0, "memory": 0.0}
        self.assertTrue(g.pressure_high(high, 60, 10, False))
        self.assertFalse(g.pressure_high(mid, 60, 10, False))   # below the limit: not engaged
        self.assertTrue(g.pressure_high(mid, 60, 10, True))     # but stays engaged until well under it
        self.assertFalse(g.pressure_high(low, 60, 10, True))

    def test_io_alone_can_engage(self):
        self.assertTrue(g.pressure_high({"cpu": 0.0, "io": 12.0, "memory": 0.0}, 60, 10, False))

    def test_read_pressure_parses_psi_files(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "cpu").write_text("some avg10=12.50 avg60=1.00 avg300=0.00 total=1\n")
            (d / "io").write_text("some avg10=9.00 avg60=1 avg300=0 total=1\nfull avg10=3.25 avg60=1 avg300=0 total=1\n")
            got = g.read_pressure(d)
        self.assertEqual((got["cpu"], got["io"], got["memory"]), (12.5, 3.25, 0.0))


class ProcReadingTest(unittest.TestCase):
    def test_stat_with_spaces_and_parentheses_in_the_name(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "77").mkdir()
            # fields after the name: state ppid ... flags(9th overall) ... nice(19th) ... start(22nd) ... policy(41st)
            f = ["S", "5", "77", "77", "0", "-1", "4194304", "0", "0", "0", "0", "0", "0", "0", "0",
                 "20", "7", "1", "0", "123456"] + ["0"] * 18 + ["3"]
            (root / "77" / "stat").write_text("77 (my (odd) app) " + " ".join(f) + "\n")
            (root / "77" / "cmdline").write_bytes(b"/usr/bin/odd\0--flag\0")
            p = g.read_proc(77, root)
        self.assertEqual((p.comm, p.ppid, p.nice, p.start, p.policy), ("my (odd) app", 5, 7, 123456, 3))
        self.assertEqual(p.cmdline, "/usr/bin/odd --flag")
        self.assertFalse(p.kernel)

    def test_focused_pid_finds_the_focused_leaf_in_the_tree(self):
        tree = {"nodes": [{"nodes": [], "floating_nodes": [{"focused": True, "pid": 4242}]},
                          {"focused": False, "pid": 1}]}
        self.assertEqual(g.focused_pid(tree), 4242)
        self.assertIsNone(g.focused_pid({"nodes": []}))


class SchemaTest(unittest.TestCase):
    def test_defaults_validate_and_compile(self):
        d = schema.defaults()["priority"]
        for k in schema.KEYS:
            if k.section == "priority":
                k.validate(d[k.name])
        s = settings_from(d)
        self.assertGreater(len(s.rules), 3)
        self.assertTrue(s.protect.search("swayctl-fx"))

    def test_bad_rules_are_refused(self):
        key = schema.lookup("priority", "rules")
        for bad in ([{"match": "(", "tier": "batch"}], [{"match": "a", "tier": "urgent"}],
                    [{"match": "a", "tier": "batch", "field": "env"}], [{"tier": "batch"}], ["a"]):
            with self.assertRaises(ValueError):
                key.validate(bad)
        self.assertEqual(key.validate([{"match": "a", "tier": "batch"}]),
                         [{"match": "a", "field": "name", "tier": "batch", "enabled": True}])

    def test_default_rules_send_builds_to_batch_and_the_language_server_to_background(self):
        s = settings_from(schema.defaults()["priority"])
        def tier(comm, cmd=""):
            return g.classify(proc(1, comm=comm, cmd=cmd), s.rules, s.protect)
        self.assertEqual(tier("cargo"), "batch")
        self.assertEqual(tier("rustc"), "batch")
        self.assertEqual(tier("java", "java -cp x org.codehaus.plexus.classworlds.launcher.Launcher"), "batch")
        self.assertEqual(tier("java", "java -Declipse.application=org.eclipse.jdt.ls.core.id1"), "background")
        self.assertIsNone(tier("java", "java -jar my-app.jar"))
        self.assertIsNone(tier("chrome"))
        self.assertIsNone(tier("swayctl-fx"))


class LiveTest(unittest.TestCase):
    """Really changes (and restores) the priority of a process this test starts."""

    def setUp(self):
        self.tag = f"31.{os.getpid() % 1000:03d}7"
        self.child = subprocess.Popen(["sleep", self.tag])
        self.addCleanup(lambda: (self.child.kill(), self.child.wait()))
        self.rules = {"match": f"sleep {re.escape(self.tag)}", "field": "cmdline", "tier": "batch"}
        time.sleep(0.05)
        # not 0 when the shell running the tests was itself given a priority
        self.orig = os.getpriority(os.PRIO_PROCESS, self.child.pid)

    def test_batch_then_restore(self):
        gov = g.Governor()
        s = settings([self.rules], protect=())
        gov.tick(s, None, 60, 10)
        self.assertEqual(os.getpriority(os.PRIO_PROCESS, self.child.pid), 19)
        self.assertEqual(os.sched_getscheduler(self.child.pid), os.SCHED_BATCH)
        self.assertIn(self.child.pid, gov.applied)
        gov.tick(settings([], protect=()), None, 60, 10)          # the rule is gone
        self.assertEqual(os.getpriority(os.PRIO_PROCESS, self.child.pid), self.orig)
        self.assertEqual(os.sched_getscheduler(self.child.pid), os.SCHED_OTHER)
        self.assertNotIn(self.child.pid, gov.applied)

    def test_restore_all_and_exited_processes_are_forgotten(self):
        gov = g.Governor()
        gov.tick(settings([self.rules], protect=()), None, 60, 10)
        self.assertEqual(gov.restore_all(), 1)
        self.assertEqual(os.getpriority(os.PRIO_PROCESS, self.child.pid), self.orig)
        gov.tick(settings([self.rules], protect=()), None, 60, 10)
        self.child.kill()
        self.child.wait()
        gov.tick(settings([self.rules], protect=()), None, 60, 10)
        self.assertEqual(gov.applied, {})

    def test_module_disable_puts_it_back(self):
        values = schema.defaults()["priority"] | {"rules": [self.rules | {"enabled": True}], "protect": [],
                                                  "pressure_guard": False, "focus_boost": False}
        m = PriorityModule(g.Governor())
        m.apply_extra("priority", values, None)
        self.assertTrue(m.tick(None, values, now=100.0))
        self.assertEqual(os.getpriority(os.PRIO_PROCESS, self.child.pid), 19)
        m.gov.new_pids = lambda: False                              # (nothing new started)
        self.assertFalse(m.tick(None, values, now=101.0))          # not due yet
        off = values | {"enabled": False}
        m.apply_extra("priority", off, {"enabled"})
        self.assertEqual(os.getpriority(os.PRIO_PROCESS, self.child.pid), self.orig)
        self.assertFalse(m.tick(None, off, now=500.0))             # off: no scanning


if __name__ == "__main__":
    unittest.main()


class WindowsTest(unittest.TestCase):
    def table(self, procs):
        return {p.pid: p for p in procs}

    def test_a_program_with_a_window_is_favored_without_a_rule(self):
        s = settings_from(schema.defaults()["priority"] | {"focus_boost": False})
        procs = self.table([proc(1, comm="newapp"), proc(2, comm="worker")])
        out = g.plan(procs, s, None, False, windows=[1])
        self.assertEqual(out[1].nice, s.focus_nice)
        self.assertNotIn(2, out)

    def test_rules_protected_and_realtime_programs_win_over_it(self):
        s = settings_from(schema.defaults()["priority"] | {"focus_boost": False})
        procs = self.table([proc(1, comm="cargo"), proc(2, comm="sway"), proc(3, comm="swayctl-fx", policy=os.SCHED_RR)])
        out = g.plan(procs, s, None, False, windows=[1, 2, 3])
        self.assertEqual(out[1].nice, 19)       # the rule says build
        self.assertNotIn(2, out)                # protected
        self.assertNotIn(3, out)                # already real-time

    def test_it_can_be_switched_off(self):
        vals = schema.defaults()["priority"] | {"favor_windows": False, "focus_boost": False}
        self.assertFalse(settings_from(vals).favor_windows)

    def test_gpu_device_detection(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for pid, target in ((10, "/dev/dri/renderD128"), (11, "/dev/null")):
                fd = root / str(pid) / "fd"
                fd.mkdir(parents=True)
                (fd / "3").symlink_to(target)
            self.assertTrue(g.draws_on_screen(10, root))
            self.assertFalse(g.draws_on_screen(11, root))
            self.assertFalse(g.draws_on_screen(12, root))   # gone

    def test_a_no_is_rechecked_later_a_yes_is_kept(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            fd = root / "10" / "fd"
            fd.mkdir(parents=True)
            gov = g.Governor()
            gov.root = root
            procs = {10: proc(10, comm="late")}
            self.assertEqual(gov.windows(procs, now=0), [])
            (fd / "3").symlink_to("/dev/dri/renderD128")
            self.assertEqual(gov.windows(procs, now=10), [])        # cached no
            self.assertEqual(gov.windows(procs, now=100), [10])     # looked again
            (fd / "3").unlink()
            self.assertEqual(gov.windows(procs, now=300), [10])     # a yes stays


class NoFlappingTest(unittest.TestCase):
    """A raised program must not be let go and raised again on every scan."""

    def test_ui_tier_is_stable_across_scans(self):
        tag = f"32.{os.getpid() % 1000:03d}9"
        child = subprocess.Popen(["sleep", tag])
        self.addCleanup(lambda: (child.kill(), child.wait()))
        time.sleep(0.05)
        s = settings([{"match": f"sleep {re.escape(tag)}", "field": "cmdline", "tier": "ui"}], protect=())
        gov = g.Governor()
        released = []
        real = gov._release
        gov._release = lambda pid: (released.append(pid), real(pid))[1]
        for _ in range(3):
            gov.tick(s, None, 60, 10)
            self.assertEqual(os.getpriority(os.PRIO_PROCESS, child.pid), s.ui_nice)
        self.assertEqual(released, [])
        gov.restore_all()


class RunBackgroundTest(unittest.TestCase):
    def test_wraps_the_command_in_the_right_order(self):
        from swayctl_center.cli import background_argv
        argv = background_argv(["--", "cargo", "build"], have=lambda t: f"/usr/bin/{t}")
        self.assertEqual(argv[:3], ["systemd-run", "--user", "--scope"])
        self.assertIn(f"--slice={g.SLICE}", argv)
        i = argv.index("--")
        self.assertEqual(argv[i + 1:], ["chrt", "--batch", "0", "nice", "-n", "39", "ionice", "-c", "3", "cargo", "build"])

    def test_without_the_helpers_it_still_runs_the_command(self):
        from swayctl_center.cli import background_argv
        self.assertEqual(background_argv(["make"], have=lambda t: None), ["make"])


class InterfaceTierTest(unittest.TestCase):
    def table(self, procs):
        return {p.pid: p for p in procs}

    def test_the_bar_is_raised_but_never_lowered_and_its_children_are_not(self):
        s = settings_from(schema.defaults()["priority"] | {"focus_boost": False})
        procs = self.table([proc(1, comm="swayctl-bar", nice=0), proc(2, 1, "okular", nice=0)])
        out = g.plan(procs, s, None, False)
        self.assertEqual(out[1].nice, -10)
        self.assertNotIn(2, out)   # launched from the bar, but not part of the interface
        already = self.table([proc(1, comm="swayctl-bar", nice=-11)])
        self.assertEqual(g.plan(already, s, None, False), {})

    def test_what_it_raised_stays_raised_on_the_next_scan(self):
        # the second scan sees the nice the first one set; that must not read as "already has more"
        s = settings_from(schema.defaults()["priority"] | {"focus_boost": False})
        raised = self.table([proc(1, comm="swayctl-bar", nice=-10)])
        self.assertEqual(g.plan(raised, s, None, False), {})                  # the program's own: left alone
        self.assertEqual(g.plan(raised, s, None, False, held=[1])[1].nice, -10)  # ours: kept

    def test_the_focused_program_stays_boosted_on_the_next_scan(self):
        s = settings_from(schema.defaults()["priority"])
        boosted = self.table([proc(5, comm="someapp", nice=s.focus_nice)])
        self.assertEqual(g.plan(boosted, s, 5, False), {})
        self.assertEqual(g.plan(boosted, s, 5, False, held=[5])[5].nice, s.focus_nice)

    def test_the_default_rules_still_demote_builds_started_from_the_bar(self):
        s = settings_from(schema.defaults()["priority"] | {"focus_boost": False})
        procs = self.table([proc(1, comm="swayctl-bar"), proc(2, 1, "cargo")])
        out = g.plan(procs, s, None, False)
        self.assertEqual((out[1].nice, out[2].nice), (-10, 19))


class CompositorTest(unittest.TestCase):
    def test_only_normal_priority_compositors_are_candidates(self):
        procs = {1: proc(1, comm="swayctl-fx"), 2: proc(2, comm="sway", policy=os.SCHED_RR),
                 3: proc(3, comm="firefox"), 4: proc(4, comm="sway", kernel=True)}
        self.assertEqual(g.realtime_candidates(procs, ("sway", "swayctl-fx")), [1])

    def test_default_settings_keep_the_compositor_realtime_and_protected(self):
        d = schema.defaults()["priority"]
        self.assertTrue(d["compositor_realtime"])
        s = settings_from(d)
        self.assertTrue(s.compositor_realtime)
        self.assertTrue(s.protect.search("swayctl-fx"))
        self.assertFalse(s.protect.search("swayctl-bar"))   # raised by a rule instead

    def _unique_sleeper(self):
        """A `sleep` under a name nothing else on the machine has (the process
        name is the executable's name), so the test touches only its own."""
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        name = f"scc-test-{os.getpid()}-{time.monotonic_ns() % 100000}"
        link = Path(d.name) / name
        link.symlink_to("/usr/bin/sleep")
        child = subprocess.Popen([str(link), "40"])
        self.addCleanup(lambda: (child.kill(), child.wait()))
        time.sleep(0.05)
        return name[:15], child   # the kernel keeps 15 characters

    @unittest.skipUnless(g.can_realtime(), "RLIMIT_RTPRIO is 0 here")
    def test_a_normal_compositor_becomes_realtime_and_is_released(self):
        name, child = self._unique_sleeper()
        gov = g.Governor()
        s = settings([], protect=(), compositor_names=(name,), focus_boost=False)
        gov.tick(s, None, 60, 10)
        self.assertEqual(os.sched_getscheduler(child.pid), os.SCHED_RR)
        self.assertEqual(os.sched_getparam(child.pid).sched_priority, 1)
        self.assertTrue(gov.status()["compositor"]["realtime"])
        gov.tick(s, None, 60, 10)   # again: nothing more to do, the policy stays
        self.assertEqual(os.sched_getscheduler(child.pid), os.SCHED_RR)
        # restore_all (the daemon quitting) leaves the compositor real-time; switching it off does not
        gov.restore_all()
        self.assertEqual(os.sched_getscheduler(child.pid), os.SCHED_RR)
        self.assertEqual(gov.release_realtime(), 1)
        self.assertEqual(os.sched_getscheduler(child.pid), os.SCHED_OTHER)

    def test_the_compositor_threads_get_the_interface_tier_and_give_it_back(self):
        name, child = self._unique_sleeper()
        before = os.getpriority(os.PRIO_PROCESS, child.pid)
        gov = g.Governor()
        s = settings([], protect=(), compositor_names=(name,), focus_boost=False)
        gov.tick(s, None, 60, 10)
        self.assertEqual(os.getpriority(os.PRIO_PROCESS, child.pid), s.ui_nice)
        self.assertIn(child.pid, gov.helpers)
        gov.tick(s, None, 60, 10)    # again: left as it is
        self.assertEqual(os.getpriority(os.PRIO_PROCESS, child.pid), s.ui_nice)
        gov.release_realtime()
        self.assertEqual(os.getpriority(os.PRIO_PROCESS, child.pid), before)
        self.assertEqual(gov.helpers, {})

    def test_when_switched_off_nothing_is_made_realtime(self):
        name, child = self._unique_sleeper()
        gov = g.Governor()
        gov.tick(settings([], protect=(), compositor_names=(name,), compositor_realtime=False,
                          focus_boost=False), None, 60, 10)
        self.assertEqual(os.sched_getscheduler(child.pid), os.SCHED_OTHER)


class InterfaceRulesTest(unittest.TestCase):
    """The visible "Favored" rules: what you look at and type into."""

    def setUp(self):
        v = schema.defaults()["priority"]
        self.s = settings_from(v)

    def tier(self, comm, cmd=""):
        return g.classify(proc(1, comm=comm, cmd=cmd), self.s.rules, self.s.protect)

    def test_the_interface_is_above_what_a_favored_app_starts(self):
        for name in ("swayctl-bar", "fuzzel", "mako", "walker"):
            self.assertEqual(self.tier(name), "ui", name)

    def test_terminals_editors_and_browsers_are_favored(self):
        for name in ("kitty", "foot", "nvim", "firefox"):
            self.assertEqual(self.tier(name), "interactive", name)
        # the IDE is favored by "favor the app you use" while focused, not by a rule: what it starts
        # inherits its priority, so it must not hold it when nobody is looking at it
        self.assertIsNone(self.tier("chodilamide-ide"))

    def test_chrome_main_and_gpu_are_favored_but_not_its_tabs(self):
        base = "/opt/google/chrome/chrome"
        self.assertEqual(self.tier("chrome", f"{base} --ozone-platform=wayland"), "interactive")
        self.assertEqual(self.tier("chrome", f"{base} --type=gpu-process --ozone-platform=wayland"), "interactive")
        self.assertIsNone(self.tier("chrome", f"{base} --type=renderer --extension-process"))
        self.assertIsNone(self.tier("chrome", f"{base} --type=zygote"))

    def test_a_build_started_in_a_terminal_is_still_heavy(self):
        procs = {1: proc(1, comm="kitty"), 2: proc(2, 1, "zsh"), 3: proc(3, 2, "cargo")}
        out = g.plan(procs, self.s, None, False)
        self.assertEqual(out[1].nice, -4)
        self.assertNotIn(2, out)       # the shell is only favored by ananicy/focus, never inherited
        self.assertEqual(out[3].nice, 19)


class NewProcessTest(unittest.TestCase):
    def test_new_pids_notices_a_start_but_not_the_first_call(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "10").mkdir()
            gov = g.Governor(proc_root=root)
            self.assertFalse(gov.new_pids())      # the first scan happens anyway
            self.assertFalse(gov.new_pids())      # nothing changed
            (root / "11").mkdir()
            (root / "self").mkdir()               # not a pid
            self.assertTrue(gov.new_pids())
            self.assertFalse(gov.new_pids())
            (root / "10").rmdir()                 # an exit is not a start
            self.assertFalse(gov.new_pids())

    def test_a_start_between_intervals_triggers_a_scan_at_once(self):
        m = PriorityModule(g.Governor())
        values = schema.defaults()["priority"] | {"pressure_guard": False, "focus_boost": False}
        m.apply_extra("priority", values, None)
        m.gov.new_pids = lambda: False
        self.assertTrue(m.tick(None, values, now=100.0))      # the first one
        self.assertFalse(m.tick(None, values, now=100.5))     # quiet: waits for the interval
        m.gov.new_pids = lambda: True                          # something started
        self.assertTrue(m.tick(None, values, now=100.6))


class CeilingTest(unittest.TestCase):
    UID = 1000
    BASE = "/user.slice/user-1000.slice/user@1000.service"

    def test_only_the_user_managers_tree_is_movable_and_never_a_service(self):
        self.assertTrue(g.movable(f"{self.BASE}/app.slice/run-p1-i2.scope", self.UID))
        self.assertTrue(g.movable(f"{self.BASE}/app.slice/app-com.google.Chrome-3585.scope", self.UID))
        self.assertFalse(g.movable("/user.slice/user-1000.slice/session-c1.scope", self.UID))   # the login session
        self.assertFalse(g.movable(f"{self.BASE}/app.slice/swayctl-center-bar.service", self.UID))
        self.assertFalse(g.movable(f"{self.BASE}/app.slice/foo.service/sub", self.UID))
        self.assertFalse(g.movable("/user.slice/user-1001.slice/user@1001.service/app.slice/x.scope", self.UID))
        self.assertFalse(g.movable(None, self.UID))

    def test_the_ceiling_is_a_share_of_all_threads(self):
        self.assertEqual(g.quota_percent(75, 16), 1200)
        self.assertEqual(g.quota_percent(80, 8), 640)
        self.assertEqual(g.quota_percent(1, 1), 1)

    def test_ensure_slice_sets_quota_and_weight_and_reports_its_cgroup(self):
        calls = []

        def run(cmd, **kw):
            calls.append(cmd)
            out = "/user.slice/x/swayctl.slice/swayctl-background.slice\n" if "show" in cmd else ""
            return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")
        path = g.ensure_slice(75, ncpu=16, run=run)
        self.assertEqual(path, "/user.slice/x/swayctl.slice/swayctl-background.slice")
        setp = next(c for c in calls if "set-property" in c)
        self.assertIn("CPUQuota=1200%", setp)
        self.assertIn("CPUWeight=20", setp)

    def test_ensure_slice_gives_none_when_systemd_refuses(self):
        fail = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, stdout="", stderr="no")
        self.assertIsNone(g.ensure_slice(75, ncpu=4, run=fail))

    def test_defaults_keep_a_quarter_free_and_less_on_battery(self):
        d = schema.defaults()["priority"]
        self.assertEqual((d["cpu_cap"], d["cpu_cap_battery"], d["gpu_limit"]), (75, 60, 80))
        self.assertLess(d["cpu_cap_battery"], d["cpu_cap"])

    def test_a_program_goes_into_the_slice_and_comes_back(self):
        """Really moves a process of this test (started under the user manager, like the IDE's)."""
        if subprocess.run(["systemctl", "--user", "is-system-running"], capture_output=True).returncode > 1:
            self.skipTest("no user manager")
        unit = f"scc-test-{os.getpid()}"
        sl = f"scctest{os.getpid()}.slice"
        tag = f"41.{os.getpid() % 1000:03d}"
        child = subprocess.Popen(["systemd-run", "--user", "--scope", "--quiet", f"--unit={unit}", "sleep", tag],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        found: list[int] = []

        def cleanup():
            for pid in found:                    # a process moved into the slice isn't the scope's to stop
                try:
                    os.kill(pid, 9)
                except OSError:
                    pass
            subprocess.run(["systemctl", "--user", "stop", f"{unit}.scope"], capture_output=True)
            subprocess.run(["systemctl", "--user", "stop", sl], capture_output=True)
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
        self.addCleanup(cleanup)
        time.sleep(0.6)
        pids = [p for p in g.scan(cmd_cache={}).values() if p.cmdline.endswith(f"sleep {tag}")]
        found.extend(p.pid for p in pids)
        if not pids or not g.movable(g.cgroup_of(pids[0].pid)):
            self.skipTest("the user manager's tree is not where this runs")
        pid = pids[0].pid
        before = g.cgroup_of(pid)
        rule = {"match": f"sleep {re.escape(tag)}$", "field": "cmdline", "tier": "batch"}
        gov = g.Governor(slice_name=sl)
        s = settings([rule], protect=(), cpu_cap=75, focus_boost=False, gpu_guard=False,
                     compositor_realtime=False)
        gov.tick(s, None, 60, 10)
        self.assertTrue(gov.slice_path, "the slice was not made")
        self.assertEqual(g.cgroup_of(pid), gov.slice_path)
        self.assertEqual(gov.status()["capped"], 1)
        self.assertEqual(int((g.CGROUP_ROOT / gov.slice_path.lstrip("/") / "cpu.max").read_text().split()[0]),
                         g.quota_percent(75, os.cpu_count() or 1) * 1000)
        gov.tick(settings([], protect=(), cpu_cap=75, focus_boost=False, gpu_guard=False,
                          compositor_realtime=False), None, 60, 10)    # the rule is gone: it comes back
        back = g.cgroup_of(pid)
        self.assertNotEqual(back, gov.slice_path)
        # where it was - or, as that scope emptied and systemd removed it, a cgroup of its own among the apps
        self.assertTrue(back == before or back.endswith("/app.slice/swayctl-center-released"), back)
        self.assertEqual(gov.status()["capped"], 0)


class GpuGuardTest(unittest.TestCase):
    def test_engages_at_the_limit_and_lets_go_well_below_it(self):
        self.assertFalse(g.gpu_engaged([70, 75, 79], 80, False))
        self.assertTrue(g.gpu_engaged([85, 90, 80], 80, False))
        self.assertTrue(g.gpu_engaged([70, 65, 62], 80, True))      # engaged: holds until under 60
        self.assertFalse(g.gpu_engaged([55, 50, 58], 80, True))
        self.assertFalse(g.gpu_engaged([], 80, True))

    def test_read_gpu_busy_takes_the_busiest_card_and_tolerates_none(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self.assertIsNone(g.read_gpu_busy(root))
            for name, v in (("card0", "12\n"), ("card1", "68\n")):
                (root / name / "device").mkdir(parents=True)
                (root / name / "device" / "gpu_busy_percent").write_text(v)
            (root / "card2" / "device").mkdir(parents=True)
            (root / "card2" / "device" / "gpu_busy_percent").write_text("n/a\n")
            self.assertEqual(g.read_gpu_busy(root), 68)

    def test_gpu_clients_counts_each_client_once_and_shares_are_a_rate(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            fi = root / "5" / "fdinfo"
            fi.mkdir(parents=True)
            body = "drm-driver:\tamdgpu\ndrm-client-id:\t7\ndrm-engine-gfx:\t{} ns\n"
            (fi / "10").write_text(body.format(2_000_000_000))
            (fi / "11").write_text(body.format(2_000_000_000))     # the same client through another fd
            (fi / "12").write_text("pos:\t0\nflags:\t02\n")           # not a drm fd
            a = g.gpu_clients([5, 99], root)
            self.assertEqual(a, {5: 2_000_000_000})
            (fi / "10").write_text(body.format(2_600_000_000))
            (fi / "11").write_text(body.format(2_600_000_000))
            b = g.gpu_clients([5], root)
            self.assertAlmostEqual(g.gpu_shares(a, b, 2.0)[5], 30.0)   # 0.6 s of a 2 s window
            self.assertEqual(g.gpu_shares(a, b, 0), {})

    def test_plan_holds_back_heavy_clients_but_not_favored_protected_or_realtime_ones(self):
        procs = {1: proc(1, 0, "mpv"), 2: proc(2, 0, "kitty"), 3: proc(3, 0, "sway"),
                 4: proc(4, 0, "rt", policy=os.SCHED_RR), 5: proc(5, 0, "chrome")}
        s = settings_from(schema.defaults()["priority"] | {"focus_boost": False})
        out = g.plan(procs, s, None, False, gpu_heavy=[1, 2, 3, 4, 99])
        self.assertEqual(out[1].nice, 10)             # held back like background work
        self.assertEqual(out[2].nice, -4)             # kitty has its own (favoring) rule
        self.assertNotIn(3, out)                      # protected
        self.assertNotIn(4, out)                      # real-time
        self.assertNotIn(5, out)                      # not heavy

    def test_the_guard_holds_back_unfocused_clients_only_while_saturated(self):
        gov = g.Governor()
        procs = {10: proc(10, comm="mpv"), 11: proc(11, comm="ide"), 12: proc(12, 11, "ide-child")}
        s = settings([], protect=(), gpu_limit=80, cpu_cap=100)
        busy = iter([90, 90, 90, 40, 20, 20])
        orig = (g.read_gpu_busy, g.gpu_clients)
        self.addCleanup(lambda: [setattr(g, n, f) for n, f in zip(("read_gpu_busy", "gpu_clients"), orig)])
        g.read_gpu_busy = lambda root=None: next(busy)
        ns = {"n": 0}

        def clients(pids, root=None):
            ns["n"] += 1
            return {10: ns["n"] * 2_000_000_000, 11: ns["n"] * 2_000_000_000, 12: ns["n"] * 1_000_000_000}
        g.gpu_clients = clients
        t = [100.0]
        real = time.monotonic
        self.addCleanup(lambda: setattr(time, "monotonic", real))
        time.monotonic = lambda: t[0]
        gov._gpu(procs, s, focus_pid=11)       # first reading while engaged: a baseline only
        self.assertEqual(gov.gpu_heavy, {})
        t[0] += 1.0
        gov._gpu(procs, s, focus_pid=11)       # now the rates are known
        self.assertEqual(set(gov.gpu_heavy), {10})   # 11 is focused, 12 is its child
        self.assertTrue(gov.gpu_engaged)
        t[0] += 1.0
        gov._gpu(procs, s, focus_pid=11)
        gov._gpu(procs, s, focus_pid=11)       # busy fell: lets go
        gov._gpu(procs, s, focus_pid=11)
        self.assertFalse(gov.gpu_engaged)
        self.assertEqual(gov.gpu_heavy, {})

    def test_no_gpu_driver_reading_means_the_guard_does_nothing(self):
        gov = g.Governor()
        orig = g.read_gpu_busy
        self.addCleanup(lambda: setattr(g, "read_gpu_busy", orig))
        g.read_gpu_busy = lambda root=None: None
        gov._gpu({}, settings([], protect=()), focus_pid=None)
        self.assertFalse(gov.gpu_engaged)
        self.assertEqual(gov.gpu_heavy, {})
