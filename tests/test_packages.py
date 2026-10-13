import base64
import hashlib
import json
import unittest

from comms.packages import MAX_PACKAGE_BYTES, PackageError, PackageStore, canonical_package, validate_package


def package(identity="demo", version=1):
    return {"schema_version": 1, "package_id": identity, "version": version,
            "crs": "EPSG:4326", "units": "degrees", "synthetic": True,
            "source": "simulated-drone", "waypoints": [{"lat": 38.4181, "lon": -110.777}]}


def transfer(store, value, chunk_size=80):
    raw = canonical_package(value)
    chunks = [raw[i:i + chunk_size] for i in range(0, len(raw), chunk_size)]
    metadata = {"package_id": value["package_id"], "version": value["version"], "size": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(), "chunks": len(chunks)}
    store.begin(metadata)
    for index, chunk in enumerate(chunks):
        store.chunk({"package_id": value["package_id"], "index": index, "data": base64.b64encode(chunk).decode()})
    return store.commit({"package_id": value["package_id"]})


class PackageTests(unittest.TestCase):
    def test_transfer_validation_and_activation_are_separate(self):
        store = PackageStore()
        self.assertEqual(transfer(store, package()), package())
        self.assertIsNone(store.active_package)
        with self.assertRaisesRegex(PackageError, "stopped"):
            store.activate("demo", stopped=False)
        store.activate("demo")
        self.assertEqual(store.summaries()[0]["status"], "active")

    def test_interrupted_out_of_order_transfer_resumes(self):
        store = PackageStore()
        raw = canonical_package(package())
        chunks = [raw[:100], raw[100:]]
        meta = {"package_id": "demo", "version": 1, "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "chunks": 2}
        store.begin(meta)
        last = {"package_id": "demo", "index": 1, "data": base64.b64encode(chunks[1]).decode()}
        store.chunk(last)
        self.assertEqual(store.chunk(last)["received"], [1])
        self.assertEqual(store.begin(meta)["received"], [1])
        with self.assertRaisesRegex(PackageError, "incomplete"):
            store.commit({"package_id": "demo"})
        store.chunk({"package_id": "demo", "index": 0, "data": base64.b64encode(chunks[0]).decode()})
        self.assertEqual(store.commit({"package_id": "demo"}), package())

    def test_corruption_rejected_and_transfer_can_restart(self):
        store = PackageStore()
        raw = canonical_package(package())
        store.begin({"package_id": "demo", "version": 1, "size": len(raw), "sha256": "0" * 64, "chunks": 1})
        store.chunk({"package_id": "demo", "index": 0, "data": base64.b64encode(raw).decode()})
        with self.assertRaisesRegex(PackageError, "integrity"):
            store.commit({"package_id": "demo"})
        self.assertNotIn("demo", store.pending)
        self.assertEqual(transfer(store, package()), package())

    def test_identity_is_immutable(self):
        store = PackageStore()
        transfer(store, package())
        with self.assertRaisesRegex(PackageError, "immutable"):
            transfer(store, package(version=2))

    def test_schema_crs_nonfinite_and_region_checks(self):
        for field, value in (("schema_version", True), ("crs", "EPSG:3857"), ("units", "radians"),
                             ("synthetic", False), ("source", "real-lidar"), ("version", 0),
                             ("waypoints", [{"lat": float("nan"), "lon": -110.777}]),
                             ("waypoints", [{"lat": 0, "lon": 0}]),
                             ("waypoints", [{"lat": 38.418, "lon": -110.777}] * 129)):
            with self.subTest(field=field, value=value):
                data = package()
                data[field] = value
                with self.assertRaises(PackageError):
                    validate_package(data)
        data = package()
        data["unknown"] = True
        with self.assertRaises(PackageError):
            validate_package(data)

    def test_memory_and_chunk_limits(self):
        store = PackageStore()
        meta = {"package_id": "a", "version": 1, "size": MAX_PACKAGE_BYTES + 1, "sha256": "0" * 64, "chunks": 40}
        with self.assertRaises(PackageError):
            store.begin(meta)
        meta.update(size=2, chunks=2)
        store.begin(meta)
        chunk = {"package_id": "a", "index": 0, "data": base64.b64encode(b"a").decode()}
        store.chunk(chunk)
        with self.assertRaisesRegex(PackageError, "conflicting"):
            store.chunk(dict(chunk, data=base64.b64encode(b"b").decode()))
        with self.assertRaisesRegex(PackageError, "aggregate"):
            store.chunk(dict(chunk, index=1, data=base64.b64encode(b"ab").decode()))
        store.begin(dict(meta, package_id="b"))
        with self.assertRaisesRegex(PackageError, "capacity"):
            store.begin(dict(meta, package_id="c"))
        self.assertEqual(sum(len(part) for upload in store.pending.values() for part in upload["chunks"].values()), 1)

    def test_noncanonical_and_duplicate_json_rejected(self):
        for raw in (json.dumps(package()).encode(), canonical_package(package()).replace(b'"version":1', b'"version":1,"version":1')):
            store = PackageStore()
            store.begin({"package_id": "demo", "version": 1, "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "chunks": 1})
            store.chunk({"package_id": "demo", "index": 0, "data": base64.b64encode(raw).decode()})
            with self.assertRaises(PackageError):
                store.commit({"package_id": "demo"})

    def test_simultaneous_commits_cannot_exceed_store_limit(self):
        store = PackageStore()
        for index in range(3):
            transfer(store, package(str(index)))
        for identity in ("3", "4"):
            raw = canonical_package(package(identity))
            store.begin({"package_id": identity, "version": 1, "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "chunks": 1})
            store.chunk({"package_id": identity, "index": 0, "data": base64.b64encode(raw).decode()})
        store.commit({"package_id": "3"})
        with self.assertRaisesRegex(PackageError, "capacity"):
            store.commit({"package_id": "4"})
        self.assertEqual(len(store.validated), 4)


if __name__ == "__main__":
    unittest.main()
