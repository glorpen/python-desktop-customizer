class Hint(object):
    def __repr__(self):
        return '<{name}: {d!r}>'.format(name=self.__class__.__name__, d=self.__dict__)
    
    def __eq__(self, other):
        return self.__class__ is other.__class__ and self.__dict__ == other.__dict__
