"""Note types (models)."""
from __future__ import annotations

import copy
import re

from ..errors import ApiError
from .base import Base

FIELD_KEYS = {"fontFamily": "font", "fontSize": "size", "description": "description", "sticky": "sticky",
              "rtl": "rtl", "plainText": "plainText", "collapsed": "collapsed",
              "excludeFromSearch": "excludeFromSearch"}
TEMPLATE_KEYS = {"questionHtml": "qfmt", "answerHtml": "afmt", "browserQuestionHtml": "bqfmt",
                 "browserAnswerHtml": "bafmt", "browserFontFamily": "bfont", "browserFontSize": "bsize"}


def template_fields(text: str, names: set[str]) -> list[str]:
    """Fields referenced by a template, in order (mirrors Anki's template tokenizer)."""
    directive = "{{=<% %>=}}"
    if text.lstrip().startswith(directive):
        text = text.lstrip()
        while text.startswith(directive):
            text = text[len(directive):]
        start, end = "<%", "%>"
    else:
        start, end = "{{", "}}"
    pattern = re.compile(re.escape(start) + r"(.*?)" + re.escape(end) + r"|<!--.*?-->", re.S)
    fields: list[str] = []
    stack: list[str] = []
    for match in pattern.finditer(text):
        if match.group(1) is None:
            continue
        token = match.group(1).lstrip("{").strip()
        if len(token) >= 2 and token[0] in "#^/":
            name = token[1:].lstrip()
            if token[0] == "/":
                if not stack or stack.pop() != name:
                    raise ApiError("validationFailed", "Mismatched template conditional.")
                continue
            stack.append(name)
        else:
            name = token.rsplit(":", 1)[-1]
        if name in names and name not in fields:
            fields.append(name)
    if stack:
        raise ApiError("validationFailed", "Unclosed template conditional.")
    return fields


class NoteTypes(Base):
    def noteTypes_list(self) -> list[dict]:
        return [{"id": str(value.id), "name": value.name} for value in self.col.models.all_names_and_ids()]

    def type_record(self, model: dict) -> dict:
        fields = []
        for field in model["flds"]:
            entry = {"name": field["name"]}
            for public, native in FIELD_KEYS.items():
                default = "" if public == "description" else ("Arial" if public == "fontFamily" else
                                                              20 if public == "fontSize" else False)
                entry[public] = field.get(native, default) if field.get(native) is not None else default
            fields.append(entry)
        templates = []
        for template in model["tmpls"]:
            entry = {"name": template["name"]}
            for public, native in TEMPLATE_KEYS.items():
                value = template.get(native)
                if not value:
                    value = 20 if public == "browserFontSize" else "Arial" if public == "browserFontFamily" else ""
                entry[public] = value
            entry["deck"] = {"id": str(template["did"])} if template.get("did") else None
            templates.append(entry)
        return {"id": str(model["id"]), "name": model["name"], "kind": "cloze" if model["type"] else "normal",
                "fields": fields, "templates": templates, "css": model["css"],
                "sortField": model["flds"][model["sortf"]]["name"] if model["flds"] else "",
                "latexHeader": model.get("latexPre", ""), "latexFooter": model.get("latexPost", ""),
                "latexSvg": bool(model.get("latexsvg", False)), "modifiedAt": self.stamp(model["mod"])}

    def noteTypes_get(self, noteType: dict) -> dict:
        return self.type_record(self.resolve(noteType, "noteType"))

    def _fill_field(self, target: dict, source: dict) -> None:
        target["name"] = source.get("name", target["name"])
        for public, native in FIELD_KEYS.items():
            if public in source:
                target[native] = source[public]

    def _fill_template(self, target: dict, source: dict) -> None:
        target["name"] = source.get("name", target["name"])
        for public, native in TEMPLATE_KEYS.items():
            if public in source:
                target[native] = source[public]
        if "deck" in source:
            target["did"] = self.resolve(source["deck"], "deck")["id"] if source["deck"] else None

    def noteTypes_create(self, name: str, fields: list[dict], templates: list[dict], kind: str = "normal",
                         css: str = "", sortField: str | None = None, latexHeader: str = "",
                         latexFooter: str = "", latexSvg: bool = False) -> dict:
        models = self.col.models
        if models.by_name(name):
            raise ApiError("conflict", "A note type with this name exists.")
        model = models.new(name)
        model.update(type=int(kind == "cloze"), css=css or model["css"], latexsvg=latexSvg)
        if latexHeader:
            model["latexPre"] = latexHeader
        if latexFooter:
            model["latexPost"] = latexFooter
        for data in fields:
            field = models.new_field(data["name"])
            self._fill_field(field, data)
            models.add_field(model, field)
        for data in templates:
            template = models.new_template(data["name"])
            self._fill_template(template, data)
            models.add_template(model, template)
        names = [field["name"] for field in model["flds"]]
        if len(names) != len(set(names)) or len({t["name"] for t in model["tmpls"]}) != len(templates):
            raise ApiError("validationFailed", "Field and template names must be unique.")
        if sortField and sortField not in names:
            raise ApiError("validationFailed", "The sort field is not one of the fields.")
        model["sortf"] = names.index(sortField) if sortField else 0
        out = self.change(models.add_dict(model))
        return self.noteTypes_get({"id": str(out.id)})

    def noteTypes_update(self, noteType: dict, patch: dict) -> dict:
        model = self.resolve(noteType, "noteType")
        mapping = {"name": "name", "css": "css", "latexHeader": "latexPre", "latexFooter": "latexPost",
                   "latexSvg": "latexsvg"}
        if "name" in patch:
            other = self.col.models.by_name(patch["name"])
            if other and other["id"] != model["id"]:
                raise ApiError("conflict", "A note type with this name exists.")
        for key, value in patch.items():
            if key == "sortField":
                names = [field["name"] for field in model["flds"]]
                if value not in names:
                    raise ApiError("validationFailed", "Sort field not found.")
                model["sortf"] = names.index(value)
            else:
                model[mapping[key]] = value
        self.change(self.col.models.update_dict(model))
        return self.noteTypes_get({"id": str(model["id"])})

    def noteTypes_editStructure(self, noteType: dict, edits: list[dict]) -> dict:
        model = self.resolve(noteType, "noteType")
        models = self.col.models
        for edit in edits:
            is_field = edit["op"].endswith("Field")
            key = "flds" if is_field else "tmpls"
            values = model[key]
            verb = edit["op"].replace("Field" if is_field else "Template", "")
            if verb == "add":
                data = edit["field" if is_field else "template"]
                value = models.new_field(data["name"]) if is_field else models.new_template(data["name"])
                (self._fill_field if is_field else self._fill_template)(value, data)
                index = edit.get("index", len(values))
                if index > len(values):
                    raise ApiError("validationFailed", "Insertion index out of range.")
                values.insert(index, value)
            else:
                value = next((v for v in values if v["name"] == edit["name"]), None)
                if value is None:
                    kind = "Field" if is_field else "Template"
                    raise ApiError("notFound", f"{kind} not found: {edit['name']}")
                if verb == "update":
                    patch = edit["patch"]
                    if is_field and "name" in patch:
                        models.rename_field(model, value, patch["name"])
                    (self._fill_field if is_field else self._fill_template)(value, patch)
                elif verb == "remove":
                    values.remove(value)
                elif verb == "move":
                    if edit["index"] >= len(values):
                        raise ApiError("validationFailed", "Move index out of range.")
                    values.remove(value)
                    values.insert(edit["index"], value)
            if not values or len({v["name"] for v in values}) != len(values):
                raise ApiError("validationFailed", "A note type needs uniquely named fields and templates.")
        self.change(models.update_dict(model))
        return self.noteTypes_get({"id": str(model["id"])})

    def noteTypes_getTemplateUsage(self, noteType: dict) -> list[dict]:
        model = self.resolve(noteType, "noteType")
        names = {field["name"] for field in model["flds"]}
        result = []
        for template in model["tmpls"]:
            question = template_fields(template["qfmt"], names)
            answer = template_fields(template["afmt"], names)
            result.append({"templateName": template["name"], "questionFields": question, "answerFields": answer})
        return result

    def noteTypes_replaceText(self, find: str, replace: str, noteTypes: list[dict] | None = None,
                              allNoteTypes: bool = False, targets: list[str] | None = None) -> dict:
        targets = targets or ["question", "answer", "css"]
        references = noteTypes if noteTypes is not None else self.noteTypes_list()
        changed = 0
        for reference in references:
            model = self.resolve(reference, "noteType")
            before = copy.deepcopy(model)
            if "css" in targets:
                model["css"] = model["css"].replace(find, replace)
            for template in model["tmpls"]:
                for target, key in (("question", "qfmt"), ("answer", "afmt")):
                    if target in targets:
                        template[key] = template[key].replace(find, replace)
            if model != before:
                self.change(self.col.models.update_dict(model))
                changed += 1
        return {"changedCount": changed}

    def noteTypes_deleteUnused(self, noteTypes: list[dict]) -> dict:
        def delete(reference: dict) -> dict:
            model = self.resolve(reference, "noteType")
            if self.col.models.use_count(model):
                raise ApiError("conflict", "This note type is in use.")
            self.change(self.col.models.remove(model["id"]))
            return {"changed": True}
        return self.many(noteTypes, delete, True)

    def noteTypes_delete(self, noteType: dict) -> dict:
        """Delete a note type together with all of its notes."""
        model = self.resolve(noteType, "noteType")
        self.change(self.col.models.remove(model["id"]))
        return {"changed": True}

    def noteTypes_addStock(self, kind: str) -> dict:
        """Add one of Anki's built-in note types (basic, basicAndReversed, basicOptionalReversed,
        basicTyping, cloze, imageOcclusion)."""
        from anki.stdmodels import StockNotetypeKind
        kinds = {"basic": StockNotetypeKind.KIND_BASIC,
                 "basicAndReversed": StockNotetypeKind.KIND_BASIC_AND_REVERSED,
                 "basicOptionalReversed": StockNotetypeKind.KIND_BASIC_OPTIONAL_REVERSED,
                 "basicTyping": StockNotetypeKind.KIND_BASIC_TYPING,
                 "cloze": StockNotetypeKind.KIND_CLOZE,
                 "imageOcclusion": StockNotetypeKind.KIND_IMAGE_OCCLUSION}
        if kind not in kinds:
            raise ApiError("invalidParams", "kind must be one of " + ", ".join(kinds))
        from anki.utils import from_json_bytes
        model = from_json_bytes(self.col._backend.get_stock_notetype_legacy(kinds[kind]))
        base, number = model["name"], 1
        while self.col.models.by_name(model["name"]):
            number += 1
            model["name"] = f"{base}-{number}"
        out = self.change(self.col.models.add_dict(model))
        return self.noteTypes_get({"id": str(out.id)})
