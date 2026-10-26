class Legacy:
    def __init__(self, owner, service=None):
        self.owner = owner
    def record(self, kind, id, fields=None):
        from ankicli.legacy import Legacy as Native
        native = Native(self.owner.app)
        if kind == 'cards':
            return self.owner.app.with_services(lambda s: native.card_info(s, id, fields))
        return self.owner.app.with_services(lambda s: native.note_info(s, id))
