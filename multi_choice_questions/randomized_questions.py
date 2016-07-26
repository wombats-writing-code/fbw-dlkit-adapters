import json

from bson import ObjectId

from dlkit.mongo.osid import record_templates as osid_records
from dlkit.mongo.assessment.objects import Question
from dlkit.mongo.assessment.sessions import ItemLookupSession
from dlkit.mongo.utilities import MongoClientValidated
from dlkit.mongo.osid.osid_errors import IllegalState
from dlkit.mongo.primitives import Id

from random import shuffle

from urllib import unquote, quote

from ...osid.base_records import ObjectInitRecord
from ...assessment.basic.multi_choice_records import MultiChoiceTextAndFilesQuestionFormRecord,\
    MultiChoiceTextAndFilesQuestionRecord


class RandomizedMCItemLookupSession(ItemLookupSession):
    """this session does "magic" unscrambling of MC question items with
        unique IDs, where the choice order has been specified in the ID.

        For example, we want MC questions to be randomized when they
        are given to the students, so each student sees the choices in
        a different order.

        Student 1:

        Q) What is X?

        a) choice 1
        b) choice 0
        c) choice 3
        d) choice 2

        Student 2:

        Q) What is X?

        a) choice 2
        b) choice 1
        c) choice 0
        d) choice 3

        But in many situations, when the student views the question again
        (i.e. they don't answer and come back, they answer but want to see
        their history, etc.), we want to record the original ordering
        of choices, to reduce confusion. This is being preserved
        in a "magic" ID for the question, which captures the
        state / parameters of the question. This ID is then stored in the
        AssessmentTaken record for that student.

        This "magic" adapter session plugs into the AssessmentSession
        and the AssessmentResultsSession and looks for any question ID
        that is flagged as a Randomized MC Question. It then knows
        to set the choice order to match the previous state. All other
        items are passed along to the unaltered MongoDB ItemLookupSession.

        This adapter session has out-of-band knowledge of the authority
        of the items it needs to deconstruct -- i.e. from the DLKit
        records implementation.
    """

    def get_item(self, item_id):
        authority = item_id.authority
        ils = ItemLookupSession(runtime=self._runtime,
                                proxy=self._proxy)
        ils.use_federated_bank_view()
        if authority == 'magic-randomize-choices-question-record':
            # for now, this will not work with aliased IDs...
            magic_identifier = unquote(item_id.identifier)
            original_identifier = magic_identifier.split('?')[0]
            choice_ids = json.loads(magic_identifier.split('?')[-1])
            original_item_id = Id(identifier=original_identifier,
                                  namespace=item_id.namespace,
                                  authority=self._catalog.ident.authority)
            orig_item = ils.get_item(original_item_id)
            orig_item.set_params(choice_ids)
            return orig_item
        else:
            return ils.get_item(item_id)


class MagicRandomizedMCItemRecord(ObjectInitRecord):
    _implemented_record_type_identifiers = [
        'magic-randomized-multiple-choice'
    ]
    def __init__(self, *args, **kwargs):
        super(MagicRandomizedMCItemRecord, self).__init__(*args, **kwargs)
        self._magic_params = None

    def get_question(self):
        question = Question(osid_object_map=self.my_osid_object._my_map['question'],
                            runtime=self.my_osid_object._runtime,
                            proxy=self.my_osid_object._proxy)
        if self._magic_params is not None:
            question.set_values(self._magic_params)
        return question

    question = property(fget=get_question)

    def set_params(self, params):
        self._magic_params = params


class MagicRandomizedMCItemFormRecord(osid_records.OsidRecord):
    """form for QTI numeric response question"""
    _implemented_record_type_identifiers = [
        'magic-randomized-multiple-choice'
    ]

    def __init__(self, osid_object_form=None):
        if osid_object_form is not None:
            self.my_osid_object_form = osid_object_form
        super(MagicRandomizedMCItemFormRecord, self).__init__()


class MultiChoiceRandomizeChoicesQuestionFormRecord(MultiChoiceTextAndFilesQuestionFormRecord):
    _implemented_record_type_identifiers = [
        'randomize-choices'
    ]

    def __init__(self, osid_object_form):
        if osid_object_form is not None:
            self.my_osid_object_form = osid_object_form
        self._init_metadata()
        if not osid_object_form.is_for_update():
            self._init_map()
        super(MultiChoiceRandomizeChoicesQuestionFormRecord, self).__init__(osid_object_form)


class MultiChoiceRandomizeChoicesQuestionRecord(MultiChoiceTextAndFilesQuestionRecord):
    _implemented_record_type_identifiers = [
        'randomize-choices'
    ]

    def __init__(self, osid_object):
        self._original_choice_order = list(osid_object._my_map['choices'])
        super(MultiChoiceRandomizeChoicesQuestionRecord, self).__init__(osid_object)
        if not self.my_osid_object._my_map['choices']:
            raise IllegalState()
        choices = self.my_osid_object._my_map['choices']
        shuffle(choices)
        self.my_osid_object._my_map['choices'] = choices

    def get_id(self):
        """override get_id to generate our "magic" ids that encode choice order"""
        choices = self.my_osid_object._my_map['choices']
        choice_ids = [c['id'] for c in choices]
        magic_identifier = quote('{0}?{1}'.format(self.my_osid_object._my_map['_id'],
                                                  json.dumps(choice_ids)))
        return Id(namespace='assessment.Item',
                  identifier=magic_identifier,
                  authority='magic-randomize-choices-question-record')

    ident = property(fget=get_id)
    id_ = property(fget=get_id)

    def get_unrandomized_choices(self):
        if not self.my_osid_object._my_map['choices']:
            raise IllegalState()
        return self._original_choice_order

    def set_values(self, choice_ids):
        """assume choice_ids is a list of choiceIds, like
        ["57978959cdfc5c42eefb36d1", "57978959cdfc5c42eefb36d0",
        "57978959cdfc5c42eefb36cf", "57978959cdfc5c42eefb36ce"]
        """
        if not self.my_osid_object._my_map['choices']:
            raise IllegalState()
        organized_choices = []
        for choice_id in choice_ids:
            choice_obj = [c for c in self._original_choice_order if c['id'] == choice_id][0]
            organized_choices.append(choice_obj)
        self.my_osid_object._my_map['choices'] = organized_choices