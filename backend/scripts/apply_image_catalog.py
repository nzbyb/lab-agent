"""Apply the bundled image catalog, or restore a previous image-only backup.

Default is read-only preview. Run from either the local backend or its container.
Does not run seeds, migrations, or ORM update hooks.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
from uuid import uuid4

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from sqlalchemy import create_engine, text
from app.config import settings, UPLOAD_DIR

CATALOG = BACKEND / "assets" / "image-catalog"
TABLES = ("labs", "equipments")


def json_value(value):
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def read_rows(conn, lock=False):
    suffix = " FOR UPDATE" if lock and conn.dialect.name == "mysql" else ""
    return {
        table: [dict(row) for row in conn.execute(
            text(f"SELECT * FROM {table} ORDER BY id{suffix}")
        ).mappings()]
        for table in TABLES
    }


def without_images(rows):
    return json_value({table: [{k: v for k, v in row.items() if k != "img"}
                              for row in data] for table, data in rows.items()})


def database_id(engine):
    url = engine.url
    # No credentials or full connection URL are written to backups/logs.
    return {"driver": url.drivername, "host": url.host,
            "port": url.port, "database": url.database}


def load_catalog():
    manifest = json.loads((CATALOG / "manifest.json").read_text(encoding="utf-8"))
    if manifest["version"] != 1 or manifest["catalog_id"] != "catalog-20261101":
        raise ValueError("Unsupported catalog")
    seen = set()
    for entry in manifest["records"]:
        table = entry["table"]
        key = (table, entry["id"])
        if table not in TABLES or key in seen:
            raise ValueError("Invalid or duplicate record")
        seen.add(key)
        asset = manifest["assets"][entry["asset"]]
        filename = asset["file"]
        if Path(filename).name != filename or not filename.endswith(".jpg"):
            raise ValueError("Unsafe asset filename")
        if hashlib.sha256((CATALOG / filename).read_bytes()).hexdigest() != asset["sha256"]:
            raise ValueError(f"Image checksum failed: {filename}")
        expected = f'/uploads/{manifest["catalog_id"]}/{filename}'
        if entry["img"] != expected or len(expected) > (100 if table == "labs" else 200):
            raise ValueError("Invalid image URL")
    return manifest


def make_plan(records, rows, rollback=False):
    indexed = {(t, r["id"]): r for t, data in rows.items() for r in data}
    plan = []
    seen = set()
    for entry in records:
        table, row_id = entry["table"], entry["id"]
        if table not in TABLES or (table, row_id) in seen:
            raise ValueError("Invalid or duplicate record")
        seen.add((table, row_id))
        row = indexed.get((table, row_id))
        if row is None or any(row.get(k) != v for k, v in entry["identity"].items()):
            raise ValueError(f"Identity mismatch: {table}/{row_id}; no changes committed")
        wanted = entry["old_img"] if rollback else entry["img"]
        if rollback and row.get("img") != entry["new_img"]:
            raise ValueError(f"Image changed since backup: {table}/{row_id}; rollback refused")
        if wanted != row.get("img"):
            plan.append({"table": table, "id": row_id, "identity": entry["identity"],
                         "old_img": row.get("img"), "new_img": wanted})
    return plan


def install_assets(manifest):
    destination = Path(UPLOAD_DIR) / manifest["catalog_id"]
    destination.mkdir(parents=True, exist_ok=True)
    for asset in manifest["assets"].values():
        target = destination / asset["file"]
        if target.exists():
            if hashlib.sha256(target.read_bytes()).hexdigest() != asset["sha256"]:
                raise ValueError(f"Existing asset differs: {target.name}")
            continue
        temporary = destination / (asset["file"] + "." + uuid4().hex + ".tmp")
        try:
            shutil.copyfile(CATALOG / asset["file"], temporary)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)


def run(engine, records, apply=False, backup_dir=None, manifest=None, rollback=False):
    backup_path = None
    with engine.begin() as conn:
        before = read_rows(conn, lock=apply)
        plan = make_plan(records, before, rollback)
        if not apply or not plan:
            print(json.dumps({"mode": "preview" if not apply else "apply",
                              "changes": len(plan), "records_checked": len(records)},
                             ensure_ascii=False))
            return plan
        if backup_dir is None:
            raise ValueError("--backup-dir is required when writing")
        backup_dir = Path(backup_dir).resolve()
        if backup_dir.is_relative_to(Path(UPLOAD_DIR).resolve()):
            raise ValueError("Backups must be outside the public uploads directory")
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
                                    + "-" + uuid4().hex[:8] + ".json")
        backup = {"version": 1, "database": database_id(engine),
                  "action": "rollback" if rollback else "apply",
                  "changes": plan, "rows_before": json_value(before)}
        with backup_path.open("x", encoding="utf-8") as stream:
            json.dump(backup, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        if manifest is not None:
            install_assets(manifest)
        for change in plan:
            table = change["table"]  # validated against TABLES by make_plan
            result = conn.execute(text(
                f"UPDATE {table} SET img=:new_img WHERE id=:id AND "
                "(img=:old_img OR (img IS NULL AND :old_img IS NULL))"
            ), {k: change[k] for k in ("new_img", "old_img", "id")})
            if result.rowcount != 1:
                raise ValueError("Concurrent image edit; transaction rolled back")
        after = read_rows(conn)
        if without_images(before) != without_images(after):
            raise ValueError("Non-image data changed; transaction rolled back")
        actual = {(t, r["id"]): r.get("img") for t, rs in after.items() for r in rs}
        if any(actual[(c["table"], c["id"])] != c["new_img"] for c in plan):
            raise ValueError("Image verification failed; transaction rolled back")
    print(json.dumps({"mode": "rollback" if rollback else "apply", "changes": len(plan),
                      "non_image_fields_unchanged": True, "backup": str(backup_path)},
                     ensure_ascii=False))
    return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write after validation (default: preview)")
    parser.add_argument("--backup-dir", type=Path)
    parser.add_argument("--rollback", type=Path, help="Restore img values from this environment's backup")
    args = parser.parse_args()
    engine = create_engine(settings.DATABASE_URL, hide_parameters=True)
    try:
        if args.rollback:
            backup = json.loads(args.rollback.read_text(encoding="utf-8"))
            if backup["version"] != 1 or backup["database"] != database_id(engine):
                raise ValueError("Backup belongs to another database environment")
            run(engine, backup["changes"], args.apply, args.backup_dir, rollback=True)
        else:
            manifest = load_catalog()
            run(engine, manifest["records"], args.apply, args.backup_dir, manifest)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
