# Method reference

Generated from the registry by `tools/gen_methods_doc.py`. `name?` is optional; `name=value` shows the default. Every collection method also accepts an optional `session`.

## API v1 (Anki-Connect compatible) — 95 methods

Same names, parameters, results and error codes as Anki-Connect's [API v1](https://git.sr.ht/~foosoft/anki-connect/tree/master/item/API_V1.md). *Operation* methods return a handle; anki-cli completes them before replying, so `operations.get` returns the final result at once.

| Method | Parameters | Kind | Notes |
|---|---|---|---|
| `access.requestPermission` |  | permission | Ask for access from a browser origin (the origin comes from the request). |
| `advanced.cards.update` | `cardId`, `patch` | advancedWrite | Set validated card metadata. |
| `advanced.reviews.import` | `reviews` | advancedWrite · operation | Import historical review rows. |
| `api.describe` |  | read | Methods, limits and runtime capabilities. |
| `api.execute` | `commands` | batch · operation | Run commands in order. |
| `application.exit` |  | lifecycle | Stop the server (needs --allow-exit). |
| `application.importFile` | `path?` | write · operation | Import a file by path. |
| `application.navigate` | `view`, `deck?` | gui · operation | Deck browser, deck overview or start reviewing. |
| `browser.getSelection` |  | read | Selected notes and cards. |
| `browser.open` | `query?`, `sort?` | gui · operation | Search in the (headless) browser. |
| `browser.select` | `cardIds?`, `noteIds?` | gui · operation | Select cards or notes in the browser. |
| `cards.get` | `id` | read | One card with its scheduling state. |
| `cards.getMany` | `ids` | read | Several cards. |
| `cards.move` | `ids`, `deck` | write | Move cards to a deck. |
| `cards.render` | `id` | read | Question and answer HTML plus CSS. |
| `cards.search` | `query`, `limit=100`, `cursor?`, `sort?` | read | Card IDs for an Anki search, paginated. |
| `cards.setFlags` | `ids`, `flag` | write | Set the flag (0–7) of cards. |
| `cards.setSuspended` | `ids`, `suspended` | write | Suspend or unsuspend cards. |
| `collection.checkIntegrity` |  | write · operation | Check and repair the database (Tools › Check Database). |
| `collection.get` |  | read | Profile, session and scheduler of the collection. |
| `collection.refresh` | `target="windows"` | refresh | Clear caches (nothing to redraw without a GUI). |
| `collection.sync` | `includeMedia=True` | lifecycle · operation | A normal sync with the stored login (full syncs: sync.run). |
| `collection.undo` |  | write · operation | Undo the last change. |
| `deckPresets.assign` | `decks`, `preset`, `rescheduleFsrs=False` | write · operation | Use a preset for decks. |
| `deckPresets.create` | `name`, `cloneFrom?` | write | Create a preset, optionally cloning another. |
| `deckPresets.delete` | `preset`, `replacement?` | write · operation | Delete a preset (with a replacement if in use). |
| `deckPresets.get` | `preset` | read | A preset with every setting. |
| `deckPresets.list` |  | read | All deck option presets. |
| `deckPresets.update` | `preset`, `name?`, `settings?`, `rescheduleFsrs=False` | write · operation | Rename or change settings of a preset. |
| `decks.create` | `name` | write | Create a deck (or return the existing one). |
| `decks.delete` | `decks`, `deleteCards` | write | Delete decks with their cards. |
| `decks.get` | `deck` | read | One deck. |
| `decks.getCounts` | `deck`, `includeChildren=True` | read | New/learning/review counts with daily limits. |
| `decks.list` |  | read | All decks. |
| `decks.update` | `deck`, `name` | write | Rename a deck. |
| `editors.openAdd` | `note?` | gui · operation | Open an Add draft. |
| `editors.openNote` | `noteId` | gui · operation | Open an editor for a note. |
| `editors.updateDraft` | `editorId`, `patch`, `mode="replace"` | gui · operation | Change a draft's fields, tags, deck or type. |
| `media.delete` | `filename` | media | Move a media file to the trash. |
| `media.get` | `filename` | read | A media file as base64. |
| `media.getDirectory` |  | read | The media folder path. |
| `media.list` | `pattern="*"` | read | Media file names matching a pattern. |
| `media.store` | `filename`, `source`, `collision="rename"`, `skipIfHash?` | media · operation | Store a media file from data, a path or a URL. |
| `noteTypes.create` | `name`, `kind="normal"`, `fields`, `templates`, `css=""`, `sortField?`, `latexHeader=""`, `latexFooter=""`, `latexSvg=False` | write | Create a note type. |
| `noteTypes.deleteUnused` | `noteTypes` | write | Delete note types that have no notes. |
| `noteTypes.editStructure` | `noteType`, `edits` | write | Add, rename, move or remove fields and templates. |
| `noteTypes.get` | `noteType` | read | A note type with fields, templates and CSS. |
| `noteTypes.getTemplateUsage` | `noteType` | read | Fields used on each template side. |
| `noteTypes.list` |  | read | All note types. |
| `noteTypes.replaceText` | `find`, `replace`, `noteTypes?`, `allNoteTypes=False`, `targets=["question", "answer", "css"]` | write | Find and replace in templates/CSS. |
| `noteTypes.update` | `noteType`, `patch` | write | Rename, restyle or change the sort field. |
| `notes.convert` | `ids`, `target`, `fields`, `templates`, `planToken` | write | Change notes to another note type using a plan. |
| `notes.create` | `noteType`, `deck`, `fields`, `tags=[]`, `duplicates?`, `rejectEmptyQuestions=True` | write | Create a note; returns its generated cards. |
| `notes.createMany` | `notes`, `atomic=False` | write | Create notes, independently or atomically. |
| `notes.delete` | `ids` | write | Delete notes and their cards. |
| `notes.findEmpty` | `criterion`, `query=""`, `limit=100`, `cursor?` | read | Notes with no cards or only empty content. |
| `notes.get` | `id` | read | One note. |
| `notes.getMany` | `ids` | read | Several notes, one item each. |
| `notes.planConversion` | `source`, `target` | read | Plan a note-type change (field/template mapping). |
| `notes.search` | `query`, `limit=100`, `cursor?`, `sort?` | read | Note IDs for an Anki search, paginated. |
| `notes.update` | `id`, `patch` | write | Change fields and/or tags. |
| `notes.validate` | `note` | read | Check whether a note can be created. |
| `notes.validateMany` | `notes` | read | Check several notes. |
| `operations.cancel` | `operationId` | lifecycle | Request cancellation (operations finish before replying). |
| `operations.get` | `operationId` | read | An operation's state and result. |
| `packages.export` | `deck`, `path`, `includeScheduling=False` | filesystem · operation | Export a deck as .apkg. |
| `packages.import` | `path` | write · operation | Import an .apkg/.colpkg. |
| `profiles.getActive` |  | read | The active profile. |
| `profiles.list` |  | read | All profiles. |
| `profiles.switch` | `name` | lifecycle · operation | Make another profile active. |
| `reviewer.answer` | `stateToken`, `rating` | write · operation | Answer the shown card. |
| `reviewer.get` |  | read | The reviewer's card, side, answers and state token. |
| `reviewer.playAudio` | `stateToken` | gui | No-op headless; play cards.answerAudio yourself. |
| `reviewer.showAnswer` | `stateToken` | gui | Show the answer side. |
| `reviewer.showQuestion` | `stateToken` | gui | Show the question side. |
| `reviewer.startTimer` | `stateToken` | gui | Restart the answer timer. |
| `reviews.getLatestId` | `deck?`, `cardIds?`, `membership="current"` | read | Newest review ID matching a filter. |
| `reviews.list` | `cardIds?`, `deck?`, `includeChildren=False`, `membership="current"`, `afterId?`, `includeManual=True`, `limit=100`, `cursor?` | read | Review history, paginated. |
| `scheduling.answer` | `cardId`, `rating`, `stateToken`, `elapsedMs=0` | write | Answer a card with a prediction's token. |
| `scheduling.answerMany` | `answers` | write | Answer several cards. |
| `scheduling.get` | `cardId` | read | Scheduling state of a card. |
| `scheduling.getDue` | `cardId`, `includeLearnAhead=False` | read | Whether a card is due now. |
| `scheduling.getQueue` | `fetchLimit=1` | read | The head of today's study queue and its counts. |
| `scheduling.predict` | `cardId` | read | Next intervals per rating and a state token for answering. |
| `scheduling.reset` | `cardIds`, `restorePosition=True`, `resetCounts=False`, `log=True` | write | Forget cards (make them new). |
| `scheduling.setDueDate` | `cardIds`, `days` | write | Set due dates with Anki's day syntax (0, 1!, 3-7). |
| `statistics.getHtml` | `deck?` | read | Anki's legacy statistics report. |
| `statistics.getReviewDays` |  | read | Reviews per day. |
| `statistics.getSummary` | `deck?` | read | Card, note and review totals. |
| `statistics.getToday` |  | read | Reviews today. |
| `tags.add` | `noteIds`, `tags` | write | Add tags to notes. |
| `tags.deleteUnused` |  | write | Remove tags no note uses. |
| `tags.list` |  | read | All tags. |
| `tags.remove` | `noteIds`, `tags` | write | Remove tags from notes. |
| `tags.replace` | `from`, `to`, `noteIds?`, `allNotes=False` | write | Rename a tag on some or all notes. |

## anki-cli extensions — 61 methods

Same conventions as v1 (references, string IDs, `{"items": [...]}` for bulk results).

| Method | Parameters | Kind | Notes |
|---|---|---|---|
| `browser.close` |  | gui | Close the browser. |
| `browser.columns` |  | read | Browser columns usable for sorting. |
| `browser.rows` | `ids`, `columns`, `mode="cards"` | read | Rendered browser rows. |
| `cards.answerAudio` | `id`, `side="question"` | read | Sound and TTS tags of a card side. |
| `cards.bury` | `ids`, `manual=True` | write | Bury cards. |
| `cards.info` | `id` | read | Anki's card info: history, ease, stability, retrievability. |
| `cards.reposition` | `ids`, `start=0`, `step=1`, `randomize=False`, `shiftExisting=False` | write | Reposition new cards. |
| `cards.unbury` | `ids` | write | Unbury cards. |
| `collection.backup` |  | filesystem | Create a backup now. |
| `collection.backups` |  | read | Backups of this profile. |
| `collection.deleteEmptyCards` | `keepNotes=True` | write | Delete empty cards. |
| `collection.emptyCards` |  | read | Cards whose templates render empty. |
| `collection.exportPackage` | `path`, `includeMedia=True`, `legacy=False` | filesystem | Write the whole collection to a .colpkg. |
| `collection.info` |  | read | Paths and counts. |
| `collection.optimize` |  | write | Vacuum and analyze the database. |
| `collection.redo` |  | write | Redo the last undone change. |
| `collection.restore` | `path`, `confirm` | lifecycle | Replace the collection with a .colpkg (backed up first). |
| `collection.undoStatus` |  | read | Labels of the next undo/redo. |
| `config.get` | `key` | read | A collection config value. |
| `config.remove` | `key` | write | Remove a config value. |
| `config.set` | `key`, `value` | write | Set a collection config value. |
| `customStudy.create` | `deck`, `mode`, `value?`, `cramKind="new"`, `cardLimit=100`, `tagsToInclude?`, `tagsToExclude?` | write | Anki's Custom Study session. |
| `customStudy.defaults` | `deck` | read | Custom Study options for a deck. |
| `decks.setCollapsed` | `deck`, `collapsed`, `scope="browser"` | write | Collapse/expand a deck. |
| `decks.setCurrent` | `deck` | write | Select the current deck. |
| `decks.tree` | `deck?` | read | Deck tree with due counts in one call. |
| `editors.close` | `editorId` | gui | Discard an editor. |
| `editors.list` |  | read | Open editors. |
| `editors.save` | `editorId` | write | Save a draft (adds or updates the note). |
| `filteredDecks.create` | `name`, `search`, `limit=100`, `order=0`, `reschedule=True`, `secondSearch?`, `secondLimit=20`, `secondOrder=0` | write | Create a filtered deck from a search. |
| `filteredDecks.empty` | `deck` | write | Return a filtered deck's cards home. |
| `filteredDecks.rebuild` | `deck` | write | Rebuild a filtered deck. |
| `fsrs.optimize` | `preset`, `search?` | read | Optimal FSRS parameters from review history. |
| `fsrs.simulate` | `preset`, `desiredRetention?`, `daysToSimulate=365` | read | FSRS workload simulation. |
| `media.check` |  | read | Unused and missing media. |
| `media.emptyTrash` |  | media | Empty the media trash. |
| `media.restoreTrash` |  | media | Restore trashed media. |
| `media.trashUnused` |  | media | Trash unused media. |
| `noteTypes.addStock` | `kind` | write | Add one of Anki's built-in note types. |
| `noteTypes.delete` | `noteType`, `confirm` | write | Delete a note type and its notes. |
| `packages.exportCsv` | `path`, `search=""`, `kind="notes"`, `withHtml=True`, `withTags=True`, `withDeck=True`, `withNoteType=True`, `withGuid=False` | filesystem | Export notes or cards as text. |
| `packages.importAnki` | `path`, `mergeNoteTypes=True`, `withScheduling=True`, `withDeckConfigs=True`, `updateNotes="ifNewer"`, `updateNoteTypes="ifNewer"` | write | Import with options; returns the log. |
| `packages.importCsv` | `path`, `deck?`, `noteType?`, `delimiter?`, `isHtml?`, `duplicates="update"`, `matchScope="noteType"`, `tags?` | write | Import CSV/TSV with Anki's importer. |
| `preferences.get` |  | read | Collection preferences. |
| `preferences.set` | `preferences` | write | Change preferences. |
| `profiles.create` | `name` | lifecycle | Create a profile. |
| `profiles.delete` | `name`, `confirm` | lifecycle | Delete a profile and its data. |
| `profiles.rename` | `name`, `newName` | lifecycle | Rename a profile. |
| `reviewer.start` | `deck?` | gui | Open a deck in the reviewer. |
| `reviewer.stop` |  | gui | Close the reviewer. |
| `reviewer.undo` |  | write | Undo the last answer and show that card again. |
| `server.info` |  | read | Version, uptime and open collections. |
| `statistics.graphs` | `search=""`, `days=365` | read | Everything behind Anki's statistics screen. |
| `statistics.studiedToday` |  | read | Anki's 'studied today' sentence. |
| `sync.account` |  | read | Sync login and options. |
| `sync.login` | `username`, `password`, `endpoint?` | lifecycle | Log in to AnkiWeb or a self-hosted server. |
| `sync.logout` |  | lifecycle | Forget the sync login. |
| `sync.media` |  | lifecycle | Sync media only. |
| `sync.run` | `mode="auto"`, `includeMedia?` | lifecycle | Sync; full syncs only with an explicit upload/download. |
| `sync.setOptions` | `syncMedia?`, `timeoutSeconds?` | lifecycle | Media sync on/off, timeout. |
| `sync.status` |  | read | Whether a sync is needed. |

## Legacy actions — 122

All Anki-Connect legacy actions at `POST /` with `action`/`version`/`params`:

`addNote`, `addNotes`, `addTags`, `answerCards`, `apiReflect`, `areDue`, `areSuspended`, `canAddNote`, `canAddNoteWithErrorDetail`, `canAddNotes`, `canAddNotesWithErrorDetail`, `cardReviews`, `cardsInfo`, `cardsModTime`, `cardsToNotes`, `changeDeck`, `clearUnusedTags`, `cloneDeckConfigId`, `createDeck`, `createModel`, `deckNameFromId`, `deckNames`, `deckNamesAndIds`, `deleteDecks`, `deleteMediaFile`, `deleteNotes`, `exportPackage`, `findAndReplaceInModels`, `findCards`, `findModelsById`, `findModelsByName`, `findNotes`, `forgetCards`, `getActiveProfile`, `getCollectionStatsHTML`, `getDeckConfig`, `getDeckStats`, `getDecks`, `getEaseFactors`, `getIntervals`, `getLatestReviewID`, `getMediaDirPath`, `getMediaFilesNames`, `getNoteTags`, `getNumCardsReviewedByDay`, `getNumCardsReviewedToday`, `getProfiles`, `getReviewsOfCards`, `getTags`, `guiAddCards`, `guiAddNoteSetData`, `guiAnswerCard`, `guiBrowse`, `guiCheckDatabase`, `guiCurrentCard`, `guiDeckBrowser`, `guiDeckOverview`, `guiDeckReview`, `guiEditNote`, `guiExitAnki`, `guiImportFile`, `guiPlayAudio`, `guiReviewActive`, `guiSelectCard`, `guiSelectNote`, `guiSelectedNotes`, `guiShowAnswer`, `guiShowQuestion`, `guiStartCardTimer`, `guiUndo`, `importPackage`, `insertReviews`, `loadProfile`, `modelFieldAdd`, `modelFieldDescriptions`, `modelFieldFonts`, `modelFieldNames`, `modelFieldRemove`, `modelFieldRename`, `modelFieldReposition`, `modelFieldSetDescription`, `modelFieldSetFont`, `modelFieldSetFontSize`, `modelFieldsOnTemplates`, `modelNameFromId`, `modelNames`, `modelNamesAndIds`, `modelStyling`, `modelTemplateAdd`, `modelTemplateRemove`, `modelTemplateRename`, `modelTemplateReposition`, `modelTemplates`, `multi`, `notesInfo`, `notesModTime`, `relearnCards`, `reloadCollection`, `removeDeckConfigId`, `removeEmptyNotes`, `removeTags`, `replaceTags`, `replaceTagsInAllNotes`, `requestPermission`, `retrieveMediaFile`, `saveDeckConfig`, `setDeckConfigId`, `setDueDate`, `setEaseFactors`, `setSpecificValueOfCard`, `storeMediaFile`, `suspend`, `suspended`, `sync`, `unsuspend`, `updateModelStyling`, `updateModelTemplates`, `updateNote`, `updateNoteFields`, `updateNoteModel`, `updateNoteTags`, `version`
