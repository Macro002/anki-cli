"""Review history, statistics, packages, collection lifecycle and advanced writes."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from typing import Any

from ..errors import ApiError
from ..util import entity_id, interval
from .base import KINDS, RATINGS, Base


class History(Base):
    # -- reviews -----------------------------------------------------------------------------

    def review_ids(self, cardIds: list[str] | None = None, deck: dict | None = None,
                   includeChildren: bool = False, membership: str = "current", afterId: str | None = None,
                   includeManual: bool = True) -> list[int]:
        clauses, args = [], []
        if cardIds is not None:
            cids = [self.card(value).id for value in cardIds]
            if not cids:
                return []
            clauses.append(f"cid in ({','.join('?' * len(cids))})")
            args.extend(cids)
        if deck:
            value = self.resolve(deck, "deck")
            dids = [value["id"]]
            if includeChildren:
                dids.extend(did for _, did in self.col.decks.children(value["id"]))
            column = "(case when odid!=0 then odid else did end)" if membership == "home" else "did"
            clauses.append(f"cid in (select id from cards where {column} in ({','.join('?' * len(dids))}))")
            args.extend(dids)
        if afterId:
            clauses.append("id>?")
            args.append(entity_id(afterId))
        if not includeManual:
            clauses.append("type not in (4,5)")
        sql = "select id from revlog" + (" where " + " and ".join(clauses) if clauses else "") + " order by id"
        return self.col.db.list(sql, *args)

    def review_record(self, row) -> dict:
        rid, cid, usn, ease, ivl, last, factor, elapsed, kind = row
        return {"id": str(rid), "cardId": str(cid), "answeredAt": self.stamp(rid / 1000),
                "rating": RATINGS[ease - 1] if 1 <= ease <= 4 else None, "interval": interval(ivl),
                "previousInterval": interval(last),
                "factor": {"encoding": "unknown", "value": max(0, factor)},
                "elapsedMs": max(0, elapsed), "kind": KINDS[kind] if 0 <= kind < len(KINDS) else "manual",
                "syncSequence": usn}

    def review_rows(self, ids: list[int]) -> list:
        if not ids:
            return []
        rows = self.col.db.all(
            f"select id,cid,usn,ease,ivl,lastIvl,factor,time,type from revlog where id in ({','.join(map(str, ids))})")
        order = {rid: index for index, rid in enumerate(ids)}
        return sorted(rows, key=lambda row: order[row[0]])

    def reviews_list(self, limit: int = 100, cursor: str | None = None, **params: Any) -> dict:
        query = {**params, "limit": limit, "cursor": cursor}
        ids = None if cursor else self.review_ids(**params)
        page = self.page(ids, "reviews.list", query)
        rows = self.review_rows([int(value) for value in page["ids"]])
        return {"items": [self.review_record(row) for row in rows], "nextCursor": page["nextCursor"]}

    def reviews_getLatestId(self, **params: Any) -> dict:
        ids = self.review_ids(**params)
        return {"id": str(ids[-1]) if ids else None}

    # -- statistics ----------------------------------------------------------------------------

    def statistics_getToday(self) -> dict:
        graphs = self.col._backend.graphs(search="", days=0)
        cutoff = self.col.sched.day_cutoff
        return {"count": graphs.today.answer_count,
                "day": datetime.fromtimestamp(cutoff - 86400).date().isoformat(),
                "nextDayAt": self.stamp(cutoff)}

    def statistics_getReviewDays(self) -> list[dict]:
        graphs = self.col._backend.graphs(search="", days=0)
        today = datetime.fromtimestamp(self.col.sched.day_cutoff - 86400).date()
        return [{"day": (today + timedelta(days=offset)).isoformat(),
                 "count": counts.learn + counts.relearn + counts.young + counts.mature + counts.filtered}
                for offset, counts in sorted(graphs.reviews.count.items(), reverse=True)]

    def deck_search(self, deck: dict | None) -> str:
        if not deck:
            return ""
        from anki.collection import SearchNode
        return self.col.build_search_string(SearchNode(deck=self.resolve(deck, "deck")["name"]))

    def statistics_getSummary(self, deck: dict | None = None) -> dict:
        query = self.deck_search(deck)
        graphs = self.col._backend.graphs(search=query, days=0)
        counts = graphs.card_counts.excluding_inactive
        cids = self.col.find_cards(query)
        if cids:
            notes = self.col.db.scalar(
                f"select count(distinct nid) from cards where id in ({','.join(map(str, cids))})")
        else:
            notes = 0
        reviews = sum(v.learn + v.relearn + v.young + v.mature + v.filtered for v in graphs.reviews.count.values())
        seconds = sum(v.learn + v.relearn + v.young + v.mature + v.filtered for v in graphs.reviews.time.values())
        return {"cardCount": len(cids), "noteCount": notes, "reviewCount": reviews, "reviewTimeMs": seconds * 1000,
                "newCount": counts.newCards, "learningCount": counts.learn + counts.relearn,
                "reviewCardCount": counts.young + counts.mature, "suspendedCount": counts.suspended}

    def statistics_getHtml(self, deck: dict | None = None) -> dict:
        stats = self.col.stats()
        stats.wholeCollection = deck is None
        if deck:
            stats.did = self.resolve(deck, "deck")["id"]
        return {"html": stats.report(), "format": "legacyReport"}

    def statistics_graphs(self, search: str = "", days: int = 365) -> dict:
        """Everything behind Anki's Statistics screen, as JSON."""
        from google.protobuf.json_format import MessageToDict
        graphs = self.col._backend.graphs(search=search, days=days)
        return MessageToDict(graphs, always_print_fields_with_no_presence=True)

    def statistics_studiedToday(self) -> dict:
        return {"text": self.col.studied_today()}

    # -- packages ------------------------------------------------------------------------------

    def packages_import(self, path: str) -> dict:
        result = self.packages_importAnki(path)
        return {"completed": result["completed"]}

    def packages_importAnki(self, path: str, mergeNoteTypes: bool = True, withScheduling: bool = True,
                            withDeckConfigs: bool = True, updateNotes: str = "ifNewer",
                            updateNoteTypes: str = "ifNewer") -> dict:
        """Import an .apkg/.colpkg with Anki's import options; returns the import log."""
        from anki.collection import ImportAnkiPackageOptions, ImportAnkiPackageRequest
        from anki.import_export_pb2 import ImportAnkiPackageUpdateCondition as Condition
        if not os.path.isfile(path):
            raise ApiError("notFound", f"Package not found: {path}")
        if path.lower().endswith(".colpkg"):
            return self.collection_restore(path)
        conditions = {"ifNewer": Condition.IMPORT_ANKI_PACKAGE_UPDATE_CONDITION_IF_NEWER,
                      "always": Condition.IMPORT_ANKI_PACKAGE_UPDATE_CONDITION_ALWAYS,
                      "never": Condition.IMPORT_ANKI_PACKAGE_UPDATE_CONDITION_NEVER}
        out = self.change(self.col.import_anki_package(ImportAnkiPackageRequest(
            package_path=path, options=ImportAnkiPackageOptions(
                merge_notetypes=mergeNoteTypes, with_scheduling=withScheduling,
                with_deck_configs=withDeckConfigs, update_notes=conditions[updateNotes],
                update_notetypes=conditions[updateNoteTypes]))))
        return {"completed": True, "log": self.import_log(out.log)}

    @staticmethod
    def import_log(log) -> dict:
        def notes(entries) -> list[str]:
            return [str(entry.id.nid) for entry in entries]
        return {"new": len(log.new), "updated": len(log.updated), "duplicate": len(log.duplicate),
                "conflicting": len(log.conflicting), "firstFieldMatch": len(log.first_field_match),
                "missingNotetype": len(log.missing_notetype), "missingDeck": len(log.missing_deck),
                "emptyFirstField": len(log.empty_first_field), "foundNotes": log.found_notes,
                "newNoteIds": [nid for nid in notes(log.new) if nid]}

    def packages_export(self, deck: dict | None, path: str, includeScheduling: bool = False,
                        includeMedia: bool = True, legacy: bool = True) -> dict:
        from anki.collection import DeckIdLimit, ExportAnkiPackageOptions
        limit = DeckIdLimit(deck_id=self.resolve(deck, "deck")["id"]) if deck else None
        directory = os.path.dirname(os.path.abspath(path))
        if not os.path.isdir(directory):
            raise ApiError("ioError", f"Directory does not exist: {directory}")
        self.col.export_anki_package(out_path=path, options=ExportAnkiPackageOptions(
            with_scheduling=includeScheduling, with_deck_configs=includeScheduling, with_media=includeMedia,
            legacy=legacy), limit=limit)
        return {"path": os.path.abspath(path)}

    def packages_importCsv(self, path: str, deck: dict | None = None, noteType: dict | None = None,
                           delimiter: str | None = None, isHtml: bool | None = None,
                           duplicates: str = "update", matchScope: str = "noteType",
                           tags: list[str] | None = None) -> dict:
        """Import CSV/TSV text using Anki's importer (auto-detects columns from the header)."""
        from anki.collection import ImportCsvRequest
        from anki.import_export_pb2 import CsvMetadata
        if not os.path.isfile(path):
            raise ApiError("notFound", f"File not found: {path}")
        delimiters = {",": CsvMetadata.COMMA, "\t": CsvMetadata.TAB, ";": CsvMetadata.SEMICOLON,
                      ":": CsvMetadata.COLON, "|": CsvMetadata.PIPE, " ": CsvMetadata.SPACE}
        metadata = self.col.get_csv_metadata(path, delimiters[delimiter] if delimiter else None)
        if deck:
            metadata.deck_id = self.resolve(deck, "deck")["id"]
        if noteType:
            metadata.global_notetype.id = self.resolve(noteType, "noteType")["id"]
        if isHtml is not None:
            metadata.is_html = isHtml
        if tags:
            metadata.global_tags.extend(tags)
        dupes = {"update": CsvMetadata.UPDATE, "preserve": CsvMetadata.PRESERVE,
                 "duplicate": CsvMetadata.DUPLICATE}
        metadata.dupe_resolution = dupes[duplicates]
        scopes = {"noteType": CsvMetadata.NOTETYPE, "noteTypeAndDeck": CsvMetadata.NOTETYPE_AND_DECK}
        metadata.match_scope = scopes[matchScope]
        out = self.change(self.col.import_csv(ImportCsvRequest(path=path, metadata=metadata)))
        return {"completed": True, "log": self.import_log(out.log)}

    def packages_exportCsv(self, path: str, search: str = "", kind: str = "notes", withHtml: bool = True,
                           withTags: bool = True, withDeck: bool = True, withNoteType: bool = True,
                           withGuid: bool = False) -> dict:
        from anki.collection import NoteIdsLimit, CardIdsLimit
        if kind == "notes":
            limit = NoteIdsLimit(note_ids=list(self.col.find_notes(search))) if search else None
            count = self.col.export_note_csv(out_path=path, limit=limit, with_html=withHtml, with_tags=withTags,
                                             with_deck=withDeck, with_notetype=withNoteType, with_guid=withGuid)
        else:
            limit = CardIdsLimit(card_ids=list(self.col.find_cards(search))) if search else None
            count = self.col.export_card_csv(out_path=path, limit=limit, with_html=withHtml)
        return {"path": os.path.abspath(path), "count": count}

    # -- whole-collection backup and restore ------------------------------------------------------

    def collection_exportPackage(self, path: str, includeMedia: bool = True, legacy: bool = False) -> dict:
        """Write a .colpkg backup of the whole collection (closes and reopens it)."""
        directory = os.path.dirname(os.path.abspath(path))
        if not os.path.isdir(directory):
            raise ApiError("ioError", f"Directory does not exist: {directory}")
        try:
            self.col.export_collection_package(out_path=path, include_media=includeMedia, legacy=legacy)
        finally:
            self.col.reopen(after_full_sync=False)
        self.after_reopen()
        return {"path": os.path.abspath(path)}

    def collection_restore(self, path: str) -> dict:
        """Replace the collection with a .colpkg (the current one is backed up first)."""
        from anki.collection import media_paths_from_col_path
        if not os.path.isfile(path):
            raise ApiError("notFound", f"Package not found: {path}")
        self.host.backup_dir.mkdir(parents=True, exist_ok=True)
        # Never replace a collection without a backup of it (a failure aborts the restore).
        self.col.create_backup(backup_folder=str(self.host.backup_dir), force=True, wait_for_completion=True)
        media_folder, media_db = media_paths_from_col_path(self.col.path)
        col_path = self.col.path
        # The backend must release the file entirely before it is replaced.
        self.col.close(downgrade=False)
        try:
            # ``backup_path`` is the package to restore from.
            self.col._backend.import_collection_package(col_path=col_path, backup_path=os.path.abspath(path),
                                                        media_folder=media_folder, media_db=media_db)
        finally:
            self.col.reopen(after_full_sync=False)
        self.after_reopen()
        return {"completed": True}

    def collection_backup(self) -> dict:
        """Create a native Anki backup now (in the profile's backups folder)."""
        self.host.backup_dir.mkdir(parents=True, exist_ok=True)
        created = self.col.create_backup(backup_folder=str(self.host.backup_dir), force=True,
                                         wait_for_completion=True)
        files = sorted(self.host.backup_dir.glob("*.colpkg"), key=os.path.getmtime)
        return {"created": bool(created), "path": str(files[-1]) if files else None}

    def collection_backups(self) -> list[dict]:
        files = sorted(self.host.backup_dir.glob("*.colpkg"), key=os.path.getmtime, reverse=True)
        return [{"path": str(path), "size": path.stat().st_size, "createdAt": self.stamp(path.stat().st_mtime)}
                for path in files]

    def after_reopen(self) -> None:
        import uuid
        self.host.session = uuid.uuid4().hex
        self.state.reviewer = {"active": False}

    # -- lifecycle -----------------------------------------------------------------------------

    def collection_get(self) -> dict:
        return {"profile": self.profile, "session": self.session,
                "scheduler": "fsrs" if self.col.get_config("fsrs", False) else "sm2"}

    def collection_info(self) -> dict:
        """Counts and paths for dashboards and health checks."""
        return {**self.collection_get(), "path": self.col.path, "mediaDir": self.col.media.dir(),
                "noteCount": self.col.note_count(), "cardCount": self.col.card_count(),
                "deckCount": len(self.col.decks.all_names_and_ids()),
                "noteTypeCount": len(self.col.models.all_names_and_ids()),
                "schedulerToday": self.col.sched.today, "dayCutoff": self.stamp(self.col.sched.day_cutoff),
                "modifiedAt": self.stamp(self.col.mod / 1000)}

    def collection_refresh(self, target: str = "windows") -> dict:
        self.col.models._clear_cache()
        return {"changed": False}

    def collection_checkIntegrity(self) -> dict:
        report, ok = self.col.fix_integrity()
        return {"problems": [] if ok else [line for line in report.splitlines() if line.strip()],
                "repaired": bool(ok)}

    def collection_undo(self) -> dict:
        status = self.col.undo_status()
        if not status.undo:
            raise ApiError("invalidState", "Nothing to undo.")
        self.col.undo()
        return {"label": status.undo, "changed": True}

    def collection_redo(self) -> dict:
        status = self.col.undo_status()
        if not status.redo:
            raise ApiError("invalidState", "Nothing to redo.")
        self.col.redo()
        return {"label": status.redo, "changed": True}

    def collection_undoStatus(self) -> dict:
        status = self.col.undo_status()
        return {"undo": status.undo or None, "redo": status.redo or None}

    def collection_optimize(self) -> dict:
        self.col.optimize()
        return {"changed": True}

    def collection_emptyCards(self) -> dict:
        """Cards whose templates now render empty (Tools > Empty Cards), grouped by note."""
        report = self.col.get_empty_cards()
        return {"report": report.report, "notes": [
            {"noteId": str(entry.note_id), "cardIds": [str(cid) for cid in entry.card_ids],
             "willDeleteNote": entry.will_delete_note} for entry in report.notes]}

    def collection_deleteEmptyCards(self, keepNotes: bool = True) -> dict:
        report = self.col.get_empty_cards()
        cids = []
        for entry in report.notes:
            ids = list(entry.card_ids)
            if keepNotes and entry.will_delete_note:
                ids = ids[1:]
            cids.extend(ids)
        if cids:
            self.change(self.col.remove_cards_and_orphaned_notes(cids))
        return {"changedCount": len(cids)}

    # -- config and preferences ----------------------------------------------------------------

    def config_get(self, key: str) -> Any:
        return self.col.get_config(key, None)

    def config_set(self, key: str, value: Any) -> dict:
        json.dumps(value)
        self.change(self.col.set_config(key, value, undoable=True))
        return {"changed": True}

    def config_remove(self, key: str) -> dict:
        self.change(self.col.remove_config(key))
        return {"changed": True}

    def preferences_get(self) -> dict:
        from google.protobuf.json_format import MessageToDict
        return MessageToDict(self.col.get_preferences(), preserving_proto_field_name=False)

    def preferences_set(self, preferences: dict) -> dict:
        from google.protobuf.json_format import ParseDict
        current = self.col.get_preferences()
        ParseDict(preferences, current)
        self.change(self.col.set_preferences(current))
        return self.preferences_get()

    # -- advanced writes -----------------------------------------------------------------------

    def advanced_cards_update(self, cardId: str, patch: dict) -> dict:
        card = self.card(cardId)
        if any(key in patch for key in ("remainingSteps", "fsrsMemory")):
            raise ApiError("unsupportedCapability", "Coupled scheduler state must change through scheduling.")
        mapping = {"intervalDays": "ivl", "sm2EasePermille": "factor", "repetitions": "reps",
                   "lapses": "lapses", "customData": "custom_data"}
        for key, value in patch.items():
            if key == "customData":
                try:
                    if not isinstance(json.loads(value or "{}"), dict):
                        raise ValueError
                except ValueError as error:
                    raise ApiError("validationFailed", "Custom data must encode a JSON object.") from error
            if key == "sm2EasePermille" and not 1300 <= value <= 65535:
                raise ApiError("validationFailed", "SM-2 ease must be between 1300 and 65535 permille.")
            setattr(card, mapping[key], value)
        self.change(self.col.update_card(card))
        return self.card_record(self.card(cardId))  # type: ignore[attr-defined]

    def advanced_reviews_import(self, reviews: list[dict]) -> dict:
        rows, seen = [], set()
        for review in reviews:
            rid = entity_id(review["id"])
            cid = self.card(review["cardId"]).id
            if rid in seen or self.col.db.scalar("select 1 from revlog where id=?", rid):
                raise ApiError("conflict", f"Review ID already exists: {rid}")
            seen.add(rid)

            def encoded(value: dict) -> int:
                if value["value"] > 2147483647:
                    raise ApiError("validationFailed", "Interval exceeds native limits.")
                return -value["value"] if value["unit"] == "seconds" else value["value"]
            ease = RATINGS.index(review["rating"]) + 1 if review["rating"] else 0
            factor, elapsed = review["factor"]["value"], review["elapsedMs"]
            if factor > 65535 or elapsed > 2147483647:
                raise ApiError("validationFailed", "Review metadata exceeds native limits.")
            rows.append((rid, cid, -1, ease, encoded(review["interval"]), encoded(review["previousInterval"]),
                         factor, elapsed, KINDS.index(review["kind"])))
        if rows:
            self.col.db.executemany(
                "insert into revlog (id,cid,usn,ease,ivl,lastIvl,factor,time,type) values (?,?,?,?,?,?,?,?,?)", rows)
        return {"changedCount": len(rows)}
