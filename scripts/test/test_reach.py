import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent
FIXTURES = SCRIPTS.parent / "fixtures"

sys.path.insert(0, str(SCRIPTS))
from lib.entry import extract_entrypoints, entrypoint_counts  # noqa: E402
from lib.imports import compute_reach, seeds_from_entrypoints  # noqa: E402
from lib.walk import walk  # noqa: E402


def fixture_files(name):
    return walk(FIXTURES / name)["files"]


def kinds(entrypoints):
    return {e["kind"] for e in entrypoints}


def details(entrypoints, kind):
    return sorted(e["detail"] for e in entrypoints if e["kind"] == kind)


class ExtractionTests(unittest.TestCase):
    def setUp(self):
        self.files = fixture_files("entrypoints")
        self.entries = extract_entrypoints(self.files)

    def test_middleware_is_found(self):
        self.assertIn("USE /api", details(self.entries, "middleware"))

    def test_blueprint_add_url_rule_is_found(self):
        self.assertIn("ROUTE /cart", details(self.entries, "http"))

    def test_django_include_resolves_to_the_included_module(self):
        included = [e for e in self.entries if e["detail"].startswith("INCLUDE")]
        self.assertEqual(len(included), 1)
        self.assertEqual(included[0]["file"], "shop/urls.py")

    def test_unresolved_include_is_marked_not_invented(self):
        files = [{"rel": "urls.py", "ext": ".py", "text": "from django.urls import include\n"
                                                          "urlpatterns = [include('missing.urls')]\n"}]
        entries = extract_entrypoints(files)
        include = next(e for e in entries if e["detail"].startswith("INCLUDE"))
        self.assertIn("unresolved", include["detail"])
        self.assertEqual(include["file"], "urls.py")

    def test_public_api_export_is_found_on_a_package_entry(self):
        self.assertTrue(any(e["kind"] == "public-api" and e["file"] == "index.ts"
                            for e in self.entries))

    def test_celery_task_is_a_consumer(self):
        self.assertIn("celery task", details(self.entries, "consumer"))

    def test_counts_cover_every_kind(self):
        counts = entrypoint_counts(self.entries)
        self.assertEqual(set(counts), {"http", "cli", "cron", "consumer",
                                       "middleware", "public-api"})
        self.assertGreater(counts["middleware"], 0)


class ConsumerSignalTests(unittest.TestCase):
    """A false consumer seed lifts every finding behind it, so the bar is high."""

    def consumers(self, rel, text):
        return [e for e in extract_entrypoints(
            [{"rel": rel, "ext": Path(rel).suffix, "text": text}])
                if e["kind"] == "consumer"]

    def test_plain_rx_subscribe_is_not_a_consumer(self):
        self.assertEqual(
            self.consumers("src/ui/FeedView.kt",
                           "class FeedView {\n  stream.subscribe { render(it) }\n}\n"),
            [])

    def test_rx_subscribe_without_io_scheduler_is_not_a_consumer(self):
        self.assertEqual(
            self.consumers("src/worker/FeedWorker.kt",
                           "class FeedWorker {\n  stream.subscribe { save(it) }\n}\n"),
            [])

    def test_rx_subscribe_on_io_in_a_worker_is_a_consumer(self):
        found = self.consumers(
            "src/worker/FeedWorker.kt",
            "class FeedWorker {\n"
            "  stream.subscribeOn(Schedulers.io).subscribe({ save(it) })\n"
            "}\n")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["line"], 2)
        self.assertEqual(found[0]["framework"], "rx")

    def test_io_scheduler_on_a_different_line_does_not_count(self):
        self.assertEqual(
            self.consumers("src/service/FeedService.kt",
                           "class FeedService {\n"
                           "  val scheduler = Schedulers.io()\n"
                           "  stream.subscribe { save(it) }\n"
                           "}\n"),
            [])

    def test_io_scheduler_outside_a_worker_or_service_path_does_not_count(self):
        self.assertEqual(
            self.consumers("src/ui/FeedView.kt",
                           "class FeedView {\n"
                           "  stream.subscribeOn(Schedulers.io).subscribe({ render(it) })\n"
                           "}\n"),
            [])

    def test_queue_signals_are_kept(self):
        celery = self.consumers("src/tasks.py", "@app.task\ndef send():\n    pass\n")
        shared = self.consumers("src/jobs.py", "@shared_task\ndef send():\n    pass\n")
        consume = self.consumers("src/queue.py", "queue.consume('jobs', handle)\n")
        kafka = self.consumers("src/kafka.ts", "const c = new Consumer({ groupId: 'g' })\n")
        self.assertTrue(celery and shared and consume and kafka)


class ConsumeSignalTests(unittest.TestCase):
    """`.consume(` is a Compose no-op as often as it is a queue call.

    On Signal-Android every remaining `consume()` was pointer-input consumption
    in gesture code, so the receiver or the line has to name a queue.
    """

    def consumers(self, rel, text):
        return [e for e in extract_entrypoints(
            [{"rel": rel, "ext": Path(rel).suffix, "text": text}])
                if e["kind"] == "consumer"]

    def test_a_compose_pointer_consume_is_not_an_entrypoint(self):
        self.assertEqual(
            self.consumers("src/ui/gesture/gesture-detector.kt",
                           "suspend fun PointerInputScope.detectTap() {\n"
                           "  awaitEachGesture {\n"
                           "    val change = event.changes.first()\n"
                           "    change.consume()\n"
                           "  }\n"
                           "}\n"),
            [])

    def test_a_bare_receiver_without_queue_wording_is_not_an_entrypoint(self):
        self.assertEqual(
            self.consumers("src/messaging/channel.ts",
                           "await channel.consume('jobs', handle)\n"),
            [])

    def test_a_consumer_receiver_is_an_entrypoint(self):
        for rel, line in (("src/kafka.ts", "await kafkaConsumer.consume(next)\n"),
                          ("src/worker/bus.ts", "consumer.consume(message)\n"),
                          ("src/pubsub/events.ts", "pubSub.subscription.consume(batch)\n")):
            found = self.consumers(rel, line)
            self.assertEqual(len(found), 1, rel)
            self.assertEqual(found[0]["line"], 1)

    def test_a_queue_receiver_is_an_entrypoint(self):
        self.assertEqual(len(self.consumers("src/broker.ts", "queue.consume(job)\n")), 1)

    def test_queue_wording_on_the_line_is_an_entrypoint(self):
        for line in ("await channel.consume('jobs', handle) // topic: jobs\n",
                     "await channel.consume('jobs', handle, { queueName: 'jobs' })\n",
                     "await channel.consume('jobs', handle, { partition: 0 })\n"):
            self.assertEqual(len(self.consumers("src/amqp.ts", line)), 1, line)

    def test_consume_in_a_comment_only_counts_when_the_line_qualifies(self):
        self.assertEqual(self.consumers("src/ui/Gesture.kt", "// it.consume()\n"), [])


class ReachScaleTests(unittest.TestCase):
    def files(self):
        return [
            {"rel": "src/routes.ts", "ext": ".ts",
             "text": "import { service } from './service'\napp.get('/x', (req, res) => {})\n"},
            {"rel": "src/service.ts", "ext": ".ts",
             "text": "import { db } from './db'\nexport const service = 1\n"},
            {"rel": "src/db.ts", "ext": ".ts",
             "text": "import { model } from '../lib/model'\nexport const db = 1\n"},
            {"rel": "lib/model.ts", "ext": ".ts", "text": "export const model = 1\n"},
            {"rel": "src/worker.ts", "ext": ".ts",
             "text": "import { job } from './job'\ncron.schedule('* * * * *', job)\n"},
            {"rel": "src/job.ts", "ext": ".ts", "text": "export const job = 1\n"},
            {"rel": "orphan.ts", "ext": ".ts", "text": "export const x = 1\n"},
        ]

    def test_each_hop_costs_one_level(self):
        files = self.files()
        seeds = {"src/routes.ts": 5}
        reach, _ = compute_reach(files, {"src/routes.ts"}, seeds=seeds)
        self.assertEqual(reach("src/routes.ts"), 5)
        self.assertEqual(reach("src/service.ts"), 4)
        self.assertEqual(reach("src/db.ts"), 3)
        self.assertEqual(reach("lib/model.ts"), 2)  # floor

    def test_cron_seed_is_four(self):
        files = self.files()
        seeds = {"src/worker.ts": 4}
        reach, _ = compute_reach(files, {"src/worker.ts"}, seeds=seeds)
        self.assertEqual(reach("src/worker.ts"), 4)
        self.assertEqual(reach("src/job.ts"), 3)

    def test_unreachable_file_is_one(self):
        files = self.files()
        reach, _ = compute_reach(files, {"src/routes.ts"}, seeds={"src/routes.ts": 5})
        self.assertEqual(reach("orphan.ts"), 1)

    def test_unreadable_file_is_zero(self):
        files = self.files()
        reach, _ = compute_reach(files, {"src/routes.ts"}, seeds={"src/routes.ts": 5},
                                 skipped={"blob.bin"})
        self.assertEqual(reach("blob.bin"), 0)

    def test_seeds_take_the_best_kind_per_file(self):
        entries = [
            {"kind": "cli", "file": "a.py"},
            {"kind": "http", "file": "a.py"},
            {"kind": "public-api", "file": "b.ts"},
        ]
        self.assertEqual(seeds_from_entrypoints(entries), {"a.py": 5, "b.ts": 3})

    def test_fixture_reach_matches_its_entrypoint_kinds(self):
        files = fixture_files("entrypoints")
        entries = extract_entrypoints(files)
        reach, _ = compute_reach(files, {e["file"] for e in entries},
                                 seeds=seeds_from_entrypoints(entries))
        self.assertEqual(reach("app.ts"), 5)
        self.assertEqual(reach("index.ts"), 4)   # package entry (3), raised by app.ts's import
        self.assertEqual(reach("worker.py"), 4)
        self.assertEqual(reach("shop/urls.py"), 5)


class ReachDiscountTests(unittest.TestCase):
    def test_reach_one_is_discounted_to_a_quarter(self):
        from lib.score import annotate
        findings = annotate([
            {"id": "a", "blast": 4, "silence": 3, "effort": 1, "reach": 5},
            {"id": "b", "blast": 4, "silence": 3, "effort": 1, "reach": 1},
        ])
        self.assertEqual(findings[0]["impact"], 4.0)
        self.assertEqual(findings[1]["impact"], 1.0)
        self.assertEqual(findings[1]["reach_discount"], 0.25)

    def test_reach_two_is_not_discounted(self):
        from lib.score import annotate
        finding = annotate([{"id": "a", "blast": 4, "silence": 3, "effort": 1, "reach": 2}])[0]
        self.assertEqual(finding["impact"], 4.0)
        self.assertNotIn("reach_discount", finding)


if __name__ == "__main__":
    unittest.main()
