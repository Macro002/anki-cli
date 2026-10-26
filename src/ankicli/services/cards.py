"""Cards and native scheduling."""
from __future__ import annotations

import time
from ..errors import ApiError
from .base import QUEUES, RATINGS, TYPES, Base


class Cards(Base):
    # -- records ---------------------------------------------------------------------------

    def state_record(self, card) -> dict:
        queue = QUEUES.get(card.queue)
        if queue is None or card.type not in TYPES:
            raise ApiError("unsupportedCapability", "Unknown card scheduling state.")
        underlying = card.queue if card.queue >= 0 else card.type
        if underlying == 0:
            due = {"kind": "position", "position": max(0, card.due)}
        elif card.queue in (1, 4) or (card.queue < 0 and card.type in (1, 3) and card.due > 1_000_000_000):
            due = {"kind": "timestamp", "at": self.stamp(card.due)}
        else:
            due = {"kind": "day", "day": card.due}
        seconds = None
        if card.type in (1, 3):
            try:
                states = self.col._backend.get_scheduling_states(card.id)
                native = states.current.normal
                if (states.current.WhichOneof("kind") == "filtered"
                        and states.current.filtered.WhichOneof("kind") == "rescheduling"):
                    native = states.current.filtered.rescheduling.original_state
                kind = native.WhichOneof("kind")
                if kind == "learning":
                    seconds = native.learning.scheduled_secs
                elif kind == "relearning":
                    seconds = native.relearning.learning.scheduled_secs
            except Exception:
                seconds = None
        memory = card.memory_state
        return {
            "type": TYPES[card.type], "queue": queue, "due": due, "intervalDays": max(0, card.ivl),
            "learningIntervalSeconds": seconds, "remainingSteps": max(0, card.left),
            "repetitions": card.reps, "lapses": card.lapses, "sm2EasePermille": card.factor,
            "fsrsMemory": ({"difficulty": memory.difficulty, "stabilityDays": memory.stability}
                           if memory else None),
            "desiredRetention": card.desired_retention or None,
        }

    def card_record(self, card) -> dict:
        return {
            "id": str(card.id), "noteId": str(card.nid), "deck": self.deck_summary(card.did),
            "homeDeck": self.deck_summary(card.odid) if card.odid else None,
            "templateIndex": card.ord, "flags": card.flags & 7, "modifiedAt": self.stamp(card.mod),
            "scheduling": self.state_record(card),
        }

    def cards_get(self, id: str) -> dict:
        return self.card_record(self.card(id))

    def cards_getMany(self, ids: list[str]) -> dict:
        return self.many(ids, self.cards_get)

    def cards_search(self, query: str, limit: int = 100, cursor: str | None = None, sort: dict | None = None) -> dict:
        return self._search("cards", query, limit, cursor, sort)  # type: ignore[attr-defined]

    def cards_render(self, id: str) -> dict:
        card = self.card(id)
        return {"cardId": str(card.id), "questionHtml": card.question(), "answerHtml": card.answer(),
                "css": card.note_type()["css"]}

    # -- writes ----------------------------------------------------------------------------

    def cards_move(self, ids: list[str], deck: dict) -> dict:
        target = self.resolve(deck, "deck")
        if target.get("dyn"):
            raise ApiError("invalidState", "Filtered decks cannot be move destinations.")

        def move(value: str) -> dict:
            card = self.card(value)
            changed = bool(card.odid or card.did != target["id"])
            if changed:
                self.change(self.col.set_deck([card.id], target["id"]))
            return {"changed": changed}
        return self.many(ids, move, True)

    def cards_setSuspended(self, ids: list[str], suspended: bool) -> dict:
        def mutate(value: str) -> dict:
            card = self.card(value)
            changed = (card.queue == -1) != suspended
            if changed:
                operation = self.col.sched.suspend_cards if suspended else self.col.sched.unsuspend_cards
                self.change(operation([card.id]))
            return {"changed": changed}
        return self.many(ids, mutate, True)

    def cards_setFlags(self, ids: list[str], flag: int) -> dict:
        def mutate(value: str) -> dict:
            card = self.card(value)
            changed = card.flags & 7 != flag
            if changed:
                self.change(self.col.set_user_flag_for_cards(flag, [card.id]))
            return {"changed": changed}
        return self.many(ids, mutate, True)

    # -- scheduling ------------------------------------------------------------------------

    def scheduling_get(self, cardId: str) -> dict:
        return self.state_record(self.card(cardId))

    def scheduling_getQueue(self, fetchLimit: int = 1) -> dict:
        queued = self.col.sched.get_queued_cards(fetch_limit=fetchLimit)
        names = {0: "new", 1: "learning", 2: "review"}
        return {"cards": [{"cardId": str(item.card.id), "queue": names.get(item.queue, "review")}
                          for item in queued.cards],
                "newCount": queued.new_count, "learningCount": queued.learning_count,
                "reviewCount": queued.review_count}

    def _state_parts(self, card, states) -> tuple:
        return (card.id, card.mod, card.queue, card.due, card.ivl, card.left, card.reps,
                states.SerializeToString().hex(), self.col.sched.today)

    def predictions(self, card, states) -> list[dict]:
        labels = self.col._backend.describe_next_states(states)
        answers = []
        for rating, label in zip(RATINGS, labels):
            state = getattr(states, rating)
            amount = None
            native = state.normal
            if state.WhichOneof("kind") == "filtered":
                if state.filtered.WhichOneof("kind") == "preview":
                    answers.append({"rating": rating, "label": label,
                                    "interval": {"value": state.filtered.preview.scheduled_secs, "unit": "seconds"}})
                    continue
                native = state.filtered.rescheduling.original_state
            kind = native.WhichOneof("kind")
            if kind == "review":
                amount = {"value": native.review.scheduled_days, "unit": "days"}
            elif kind == "learning":
                amount = {"value": native.learning.scheduled_secs, "unit": "seconds"}
            elif kind == "relearning":
                amount = {"value": native.relearning.learning.scheduled_secs, "unit": "seconds"}
            answers.append({"rating": rating, "label": label, "interval": amount})
        return answers

    def scheduling_predict(self, cardId: str) -> dict:
        card = self.card(cardId)
        states = self.col._backend.get_scheduling_states(card.id)
        return {"cardId": str(card.id), "source": "scheduler",
                "stateToken": self.token("scheduler", self._state_parts(card, states)),
                "answers": self.predictions(card, states)}

    def scheduling_getDue(self, cardId: str, includeLearnAhead: bool = False) -> dict:
        card = self.card(cardId)
        now = time.time()
        due = ahead = False
        if card.queue in (1, 4):
            due = card.due <= now
            ahead = not due and card.due <= now + self.col.get_config("collapseTime", 1200)
        elif card.queue in (2, 3):
            due = card.due <= self.col.sched.today
        return {"cardId": str(card.id), "dueNow": due,
                "available": due or card.queue == 0 or (includeLearnAhead and ahead), "learnAhead": ahead}

    def answer_native(self, card, rating: str, states=None, elapsed_ms: int | None = None) -> None:
        from anki.scheduler.v3 import CardAnswer
        if states is None:
            states = self.col._backend.get_scheduling_states(card.id)
        native = {"again": CardAnswer.AGAIN, "hard": CardAnswer.HARD,
                  "good": CardAnswer.GOOD, "easy": CardAnswer.EASY}[rating]
        if elapsed_ms is None:
            started = self.state.timer_started.pop(card.id, None)
            elapsed_ms = int((time.time() - started) * 1000) if started else 0
        card.timer_started = time.time() - elapsed_ms / 1000
        answer = self.col.sched.build_answer(card=card, states=states, rating=native)
        answer.milliseconds_taken = max(0, min(int(elapsed_ms), card.time_limit()))
        try:
            self.change(self.col.sched.answer_card(answer))
        except Exception as error:
            if "not at top of queue" not in str(error):
                raise
            # Anki's cached study queue only accepts its head card. Answering any other
            # card (Anki-Connect's answerCards, scheduling.answer) needs the queue
            # refreshed: a no-op card write does that, and folding both steps into one
            # named undo entry keeps the user's undo history intact.
            step = self.col.add_custom_undo_entry("Answer Card")
            self.col.update_card(self.col.get_card(card.id))
            self.col.sched.answer_card(answer)
            self.col.merge_undo_entries(step)

    def scheduling_answer(self, cardId: str, rating: str, stateToken: str, elapsedMs: int = 0) -> dict:
        card = self.card(cardId)
        if card.queue < 0 or card.queue == 4:
            raise ApiError("invalidState", "Suspended, buried and preview cards cannot be answered.")
        states = self.col._backend.get_scheduling_states(card.id)
        self.check_token(stateToken, "scheduler", self._state_parts(card, states),
                         "The card changed since it was predicted; predict again.")
        self.answer_native(card, rating, states, elapsedMs)
        review_id = self.col.db.scalar("select max(id) from revlog where cid=?", card.id)
        return {"cardId": str(card.id), "reviewId": str(review_id) if review_id else None,
                "scheduling": self.state_record(self.card(card.id))}

    def scheduling_answerMany(self, answers: list[dict]) -> dict:
        return self.many(answers, lambda data: self.scheduling_answer(**data))

    def scheduling_reset(self, cardIds: list[str], restorePosition: bool = True, resetCounts: bool = False,
                         log: bool = True) -> dict:
        from anki.scheduler.base import ScheduleCardsAsNew

        def reset(value: str) -> dict:
            card = self.card(value)
            self.change(self.col._backend.schedule_cards_as_new(ScheduleCardsAsNew(
                card_ids=[card.id], restore_position=restorePosition, reset_counts=resetCounts,
                log=log)))
            return {"changed": True}
        return self.many(cardIds, reset, True)

    def scheduling_setDueDate(self, cardIds: list[str], days: str) -> dict:
        def set_due(value: str) -> dict:
            card = self.card(value)
            self.change(self.col.sched.set_due_date([card.id], days))
            return {"changed": True}
        return self.many(cardIds, set_due, True)

    # -- extras: bury, reposition, card info -----------------------------------------------------

    def cards_bury(self, ids: list[str], manual: bool = True) -> dict:
        cids = [self.card(value).id for value in ids]
        out = self.change(self.col.sched.bury_cards(cids, manual=manual))
        return {"changedCount": getattr(out, "count", len(cids))}

    def cards_unbury(self, ids: list[str]) -> dict:
        cids = [self.card(value).id for value in ids]
        self.change(self.col.sched.unbury_cards(cids))
        return {"changedCount": len(cids)}

    def cards_reposition(self, ids: list[str], start: int = 0, step: int = 1, randomize: bool = False,
                         shiftExisting: bool = False) -> dict:
        cids = [self.card(value).id for value in ids]
        out = self.change(self.col.sched.reposition_new_cards(
            card_ids=cids, starting_from=start, step_size=step, randomize=randomize,
            shift_existing=shiftExisting))
        return {"changedCount": getattr(out, "count", len(cids))}

    def cards_info(self, id: str) -> dict:
        """Anki's card info panel as data: added date, due, ease, retrievability, history."""
        from google.protobuf.json_format import MessageToDict
        card = self.card(id)
        stats = self.col.card_stats_data(card.id)
        return MessageToDict(stats, preserving_proto_field_name=False, always_print_fields_with_no_presence=True)

    def cards_answerAudio(self, id: str, side: str = "question") -> list[dict]:
        """Audio and TTS tags of one side, in playback order."""
        card = self.card(id)
        tags = card.question_av_tags() if side == "question" else card.answer_av_tags()
        out = []
        for tag in tags:
            if hasattr(tag, "filename"):
                out.append({"kind": "sound", "filename": tag.filename})
            else:
                out.append({"kind": "tts", "text": tag.field_text, "lang": tag.lang,
                            "voices": list(tag.voices), "speed": tag.speed})
        return out
