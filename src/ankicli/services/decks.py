"""Decks, deck presets, filtered decks and custom study."""
from __future__ import annotations

import copy
from typing import Any

from ..errors import ApiError
from .base import Base

PRESET_KEYS = {
    "learnStepsMinutes": "learn_steps", "relearnStepsMinutes": "relearn_steps",
    "fsrsParameters4": "fsrs_params_4", "fsrsParameters5": "fsrs_params_5", "fsrsParameters6": "fsrs_params_6",
    "newPerDay": "new_per_day", "newPerDayMinimum": "new_per_day_minimum",
    "reviewsPerDay": "reviews_per_day", "initialEase": "initial_ease",
    "easyMultiplier": "easy_multiplier", "hardMultiplier": "hard_multiplier",
    "lapseMultiplier": "lapse_multiplier", "intervalMultiplier": "interval_multiplier",
    "maximumIntervalDays": "maximum_review_interval", "minimumLapseIntervalDays": "minimum_lapse_interval",
    "graduatingGoodDays": "graduating_interval_good", "graduatingEasyDays": "graduating_interval_easy",
    "leechThreshold": "leech_threshold", "answerTimeLimitSeconds": "cap_answer_time_to_secs",
    "desiredRetention": "desired_retention", "historicalRetention": "historical_retention",
    "easyDaysPercentages": "easy_days_percentages", "ignoreReviewsBefore": "ignore_revlogs_before_date",
    "parameterSearch": "param_search", "questionDisplaySeconds": "seconds_to_show_question",
    "answerDisplaySeconds": "seconds_to_show_answer", "disableAutoplay": "disable_autoplay",
    "showTimer": "show_timer", "stopTimerOnAnswer": "stop_timer_on_answer", "waitForAudio": "wait_for_audio",
    "skipQuestionOnAnswerReplay": "skip_question_when_replaying_answer",
    "buryNew": "bury_new", "buryReviews": "bury_reviews", "buryDayLearning": "bury_interday_learning",
}
PRESET_ENUMS = {
    "newInsertOrder": ("new_card_insert_order", ["due", "random"]),
    "newGatherOrder": ("new_card_gather_priority", ["deck", "lowestPosition", "highestPosition", "randomNotes",
                                                     "randomCards", "deckThenRandomNotes"]),
    "newSortOrder": ("new_card_sort_order", ["template", "none", "templateThenRandom",
                                              "randomNoteThenTemplate", "randomCard"]),
    "reviewOrder": ("review_order", ["day", "dayThenDeck", "deckThenDay", "intervalAscending",
                                     "intervalDescending", "easeAscending", "easeDescending",
                                     "retrievabilityAscending", "random", "added", "reverseAdded",
                                     "retrievabilityDescending", "relativeOverdueness"]),
    "newMix": ("new_mix", ["mixed", "afterReviews", "beforeReviews"]),
    "dayLearningMix": ("interday_learning_mix", ["mixed", "afterReviews", "beforeReviews"]),
    "leechAction": ("leech_action", ["suspend", "tagOnly"]),
    "questionAction": ("question_action", ["showAnswer", "showReminder"]),
    "answerAction": ("answer_action", ["buryCard", "again", "good", "hard", "showReminder"]),
}


class Decks(Base):
    # -- decks -----------------------------------------------------------------------------

    def deck_record(self, deck: dict) -> dict:
        return {"id": str(deck["id"]), "name": deck["name"], "kind": "filtered" if deck.get("dyn") else "normal",
                "presetId": None if deck.get("dyn") else str(deck["conf"])}

    def decks_list(self) -> list[dict]:
        return [self.deck_record(self.col.decks.get(entry.id)) for entry in self.col.decks.all_names_and_ids()]

    def decks_get(self, deck: dict) -> dict:
        return self.deck_record(self.resolve(deck, "deck"))

    def decks_create(self, name: str) -> dict:
        existing = self.col.decks.by_name(name)
        if existing:
            return self.deck_record(existing)
        out = self.change(self.col.decks.add_normal_deck_with_name(name))
        return self.deck_record(self.col.decks.get(out.id))

    def decks_update(self, deck: dict, name: str) -> dict:
        value = self.resolve(deck, "deck")
        other = self.col.decks.id_for_name(name)
        if other and other != value["id"]:
            raise ApiError("conflict", "A deck with this name exists.")
        self.change(self.col.decks.rename(value["id"], name))
        return self.deck_record(self.col.decks.get(value["id"]))

    def decks_delete(self, decks: list[dict], deleteCards: bool = True) -> dict:
        if deleteCards is not True:
            raise ApiError("invalidParams", "Deleting a deck always deletes its cards; pass deleteCards=true.")

        def delete(reference: dict) -> dict:
            value = self.resolve(reference, "deck")
            self.change(self.col.decks.remove([value["id"]]))
            return {"changed": True}
        return self.many(decks, delete, True)

    def _tree_node(self, deck_id: int):
        def find(node):
            if node.deck_id == deck_id:
                return node
            for child in node.children:
                match = find(child)
                if match:
                    return match
            return None
        return find(self.col.sched.deck_due_tree())

    def decks_getCounts(self, deck: dict, includeChildren: bool = True) -> dict:
        value = self.resolve(deck, "deck")
        node = self._tree_node(value["id"])
        # Anki leaves an empty Default deck out of the tree: it exists, nothing is due.
        counts = [node.new_count, node.learn_count, node.review_count] if node else [0, 0, 0]
        if node and not includeChildren:
            for child in node.children:
                counts = [max(0, a - b) for a, b in zip(counts, [child.new_count, child.learn_count,
                                                                    child.review_count])]
        dids = [value["id"]] + ([did for _, did in self.col.decks.children(value["id"])] if includeChildren else [])
        total = self.col.db.scalar(
            f"select count() from cards where did in ({','.join(map(str, dids))}) "
            f"or odid in ({','.join(map(str, dids))})")
        return {"deckId": str(value["id"]), "new": counts[0], "learning": counts[1], "review": counts[2],
                "total": total}

    def decks_tree(self, deck: dict | None = None) -> dict:
        """The whole deck tree with Anki's due counts (daily limits applied) in one call."""
        root = self.col.sched.deck_due_tree()
        if deck is not None:
            root = self._tree_node(self.resolve(deck, "deck")["id"])
            if root is None:
                raise ApiError("notFound", "Deck counts are unavailable.")
        totals = dict(self.col.db.all(
            "select (case when odid!=0 then odid else did end), count() from cards group by 1"))

        def node(entry, path: str) -> dict:
            name = f"{path}::{entry.name}" if path else entry.name
            children = [node(child, name) for child in entry.children]
            own = totals.get(entry.deck_id, 0)
            return {"id": str(entry.deck_id), "name": name, "shortName": entry.name, "level": entry.level,
                    "collapsed": entry.collapsed, "filtered": entry.filtered,
                    "new": entry.new_count, "learning": entry.learn_count, "review": entry.review_count,
                    "total": own + sum(child["total"] for child in children), "children": children}
        if deck is None:
            return {"children": [node(child, "") for child in root.children]}
        parent = self.col.decks.name(root.deck_id).rsplit("::", 1)
        return node(root, parent[0] if len(parent) == 2 else "")

    def decks_setCollapsed(self, deck: dict, collapsed: bool, scope: str = "browser") -> dict:
        from anki.decks import DeckCollapseScope
        value = self.resolve(deck, "deck")
        native = DeckCollapseScope.BROWSER if scope == "browser" else DeckCollapseScope.REVIEWER
        self.change(self.col.decks.set_collapsed(deck_id=value["id"], collapsed=collapsed, scope=native))
        return {"changed": True}

    def decks_setCurrent(self, deck: dict) -> dict:
        value = self.resolve(deck, "deck")
        self.change(self.col.decks.set_current(value["id"]))
        return self.deck_record(value)

    # -- filtered decks and custom study ---------------------------------------------------------

    def filteredDecks_create(self, name: str, search: str, limit: int = 100, order: int = 0,
                             reschedule: bool = True, secondSearch: str | None = None,
                             secondLimit: int = 20, secondOrder: int = 0) -> dict:
        deck = self.col.sched.get_or_create_filtered_deck(deck_id=0)
        deck.name = name
        config = deck.config
        config.reschedule = reschedule
        del config.search_terms[:]
        config.search_terms.add(search=search, limit=limit, order=order)
        if secondSearch:
            config.search_terms.add(search=secondSearch, limit=secondLimit, order=secondOrder)
        out = self.change(self.col.sched.add_or_update_filtered_deck(deck))
        return self.deck_record(self.col.decks.get(out.id))

    def filteredDecks_rebuild(self, deck: dict) -> dict:
        value = self.resolve(deck, "deck")
        if not value.get("dyn"):
            raise ApiError("invalidState", "Not a filtered deck.")
        out = self.change(self.col.sched.rebuild_filtered_deck(value["id"]))
        return {"changedCount": out.count}

    def filteredDecks_empty(self, deck: dict) -> dict:
        value = self.resolve(deck, "deck")
        if not value.get("dyn"):
            raise ApiError("invalidState", "Not a filtered deck.")
        self.change(self.col.sched.empty_filtered_deck(value["id"]))
        return {"changed": True}

    def customStudy_defaults(self, deck: dict) -> dict:
        from google.protobuf.json_format import MessageToDict
        value = self.resolve(deck, "deck")
        return MessageToDict(self.col.sched.custom_study_defaults(value["id"]))

    def customStudy_create(self, deck: dict, mode: str, value: int | None = None,
                           cramKind: str = "new", cardLimit: int = 100,
                           tagsToInclude: list[str] | None = None, tagsToExclude: list[str] | None = None) -> dict:
        """Anki's Custom Study: extra new/review cards, forgotten cards, review ahead,
        preview new cards, or cram by state and tags."""
        from anki.scheduler.base import CustomStudyRequest
        target = self.resolve(deck, "deck")
        request = CustomStudyRequest(deck_id=target["id"])
        if mode == "newLimitDelta":
            request.new_limit_delta = int(value or 0)
        elif mode == "reviewLimitDelta":
            request.review_limit_delta = int(value or 0)
        elif mode == "forgotDays":
            request.forgot_days = int(value or 1)
        elif mode == "reviewAheadDays":
            request.review_ahead_days = int(value or 1)
        elif mode == "previewDays":
            request.preview_days = int(value or 1)
        elif mode == "cram":
            kinds = {"due": 0, "new": 1, "review": 2, "all": 3}
            request.cram.kind = kinds[cramKind]
            request.cram.card_limit = cardLimit
            request.cram.tags_to_include.extend(tagsToInclude or [])
            request.cram.tags_to_exclude.extend(tagsToExclude or [])
        else:
            raise ApiError("invalidParams", "mode must be newLimitDelta, reviewLimitDelta, forgotDays, "
                                            "reviewAheadDays, previewDays or cram")
        self.change(self.col.sched.custom_study(request))
        return {"changed": True}

    # -- presets ---------------------------------------------------------------------------

    def preset(self, reference: dict):
        values = self.col.decks.all_config()
        value = next((v for v in values if str(v["id"]) == reference.get("id") or v["name"] == reference.get("name")),
                     None)
        if value is None:
            raise ApiError("notFound", f"Preset not found: {reference.get('name', reference.get('id'))}")
        return self.col._backend.get_deck_config(value["id"])

    def preset_record(self, config) -> dict:
        settings: dict[str, Any] = {}
        inner = config.config
        for public, native in PRESET_KEYS.items():
            value = getattr(inner, native)
            settings[public] = list(value) if inner.DESCRIPTOR.fields_by_name[native].is_repeated else value
        for public, (native, names) in PRESET_ENUMS.items():
            index = getattr(inner, native)
            settings[public] = names[index] if index < len(names) else names[0]
        return {"id": str(config.id), "name": config.name, "settings": settings,
                "modifiedAt": self.stamp(config.mtime_secs)}

    def deckPresets_list(self) -> list[dict]:
        return [self.summary(value) for value in self.col.decks.all_config()]

    def deckPresets_get(self, preset: dict) -> dict:
        return self.preset_record(self.preset(preset))

    def _update_request(self, deck_id: int, configs, remove=(), reschedule: bool = False):
        from anki.decks import UpdateDeckConfigs
        current = self.col.decks.get_deck_configs_for_update(deck_id)
        return UpdateDeckConfigs(
            target_deck_id=deck_id, configs=configs, removed_config_ids=remove, mode=0,
            limits=current.current_deck.limits, card_state_customizer=current.card_state_customizer,
            new_cards_ignore_review_limit=current.new_cards_ignore_review_limit, fsrs=current.fsrs,
            apply_all_parent_limits=current.apply_all_parent_limits, fsrs_reschedule=reschedule,
            fsrs_health_check=current.fsrs_health_check)

    def deckPresets_create(self, name: str, cloneFrom: dict | None = None) -> dict:
        if any(value["name"] == name for value in self.col.decks.all_config()):
            raise ApiError("conflict", "A preset with this name exists.")
        current = self.col.decks.get_deck_configs_for_update(1)
        config = copy.deepcopy(self.preset(cloneFrom) if cloneFrom else current.defaults)
        config.id, config.name = 0, name
        # The update selects the last config for the target deck; keep Default's selection.
        selected = self.preset({"id": str(current.current_deck.config_id)})
        self.change(self.col.decks.update_deck_configs(self._update_request(1, [config, selected])))
        return self.deckPresets_get({"name": name})

    def deckPresets_update(self, preset: dict, name: str | None = None, settings: dict | None = None,
                           rescheduleFsrs: bool = False) -> dict:
        config = copy.deepcopy(self.preset(preset))
        if name:
            config.name = name
        for public, value in (settings or {}).items():
            if public in PRESET_ENUMS:
                native, names = PRESET_ENUMS[public]
                setattr(config.config, native, names.index(value))
            else:
                native = PRESET_KEYS[public]
                destination = getattr(config.config, native)
                if isinstance(value, list):
                    destination[:] = value
                else:
                    setattr(config.config, native, value)
        current = self.col.decks.get_deck_configs_for_update(1)
        selected = self.preset({"id": str(current.current_deck.config_id)})
        configs = [config] if selected.id == config.id else [config, selected]
        self.change(self.col.decks.update_deck_configs(self._update_request(1, configs, reschedule=rescheduleFsrs)))
        return self.deckPresets_get({"id": str(config.id)})

    def deckPresets_assign(self, decks: list[dict], preset: dict, rescheduleFsrs: bool = False) -> dict:
        config = self.preset(preset)

        def assign(reference: dict) -> dict:
            deck = self.resolve(reference, "deck")
            if deck.get("dyn"):
                raise ApiError("invalidState", "Filtered decks have no preset.")
            changed = deck["conf"] != config.id
            if changed:
                self.change(self.col.decks.update_deck_configs(
                    self._update_request(deck["id"], [config], reschedule=rescheduleFsrs)))
            return {"changed": changed}
        return self.many(decks, assign, True)

    def deckPresets_delete(self, preset: dict, replacement: dict | None = None) -> dict:
        config = self.preset(preset)
        if config.id == 1:
            raise ApiError("conflict", "The Default preset cannot be deleted.")
        dependent = [deck for deck in self.decks_list() if deck["presetId"] == str(config.id)]
        if dependent and replacement is None:
            raise ApiError("conflict", "This preset is in use; pass a replacement.")
        if replacement:
            chosen = self.preset(replacement)
            if chosen.id == config.id:
                raise ApiError("conflict", "The replacement is the preset being deleted.")
            for deck in dependent:
                self.change(self.col.decks.update_deck_configs(self._update_request(int(deck["id"]), [chosen])))
        default_deck = self.col.decks.get(1)
        selected = self.preset({"id": str(default_deck["conf"])})
        self.change(self.col.decks.update_deck_configs(self._update_request(1, [selected], [config.id])))
        return {"changed": True}

    # -- FSRS ------------------------------------------------------------------------------

    def fsrs_optimize(self, preset: dict, search: str | None = None) -> dict:
        """Compute optimal FSRS parameters for a preset from its review history (not saved)."""
        config = self.preset(preset)
        query = search or config.config.param_search or f'preset:"{config.name}" -is:suspended'
        response = self.col._backend.compute_fsrs_params(
            search=query, ignore_revlogs_before_ms=0, current_params=list(config.config.fsrs_params_6),
            num_of_relearning_steps=len(config.config.relearn_steps), health_check=False)
        return {"parameters": list(response.params), "reviewCount": response.fsrs_items}

    def fsrs_simulate(self, preset: dict, desiredRetention: float | None = None, daysToSimulate: int = 365) -> dict:
        """Workload estimate for a desired retention (Anki's FSRS simulator)."""
        from google.protobuf.json_format import MessageToDict
        from anki.scheduler_pb2 import SimulateFsrsReviewRequest
        config = self.preset(preset)
        inner = config.config
        request = SimulateFsrsReviewRequest(
            params=list(inner.fsrs_params_6) or [], desired_retention=desiredRetention or inner.desired_retention,
            deck_size=self.col.card_count(), days_to_simulate=daysToSimulate,
            new_limit=inner.new_per_day, review_limit=inner.reviews_per_day,
            max_interval=inner.maximum_review_interval, search=f'preset:"{config.name}"',
            new_cards_ignore_review_limit=True, easy_days_percentages=list(inner.easy_days_percentages),
            learning_step_count=len(inner.learn_steps), relearning_step_count=len(inner.relearn_steps))
        response = self.col._backend.simulate_fsrs_review(request)
        return MessageToDict(response)
