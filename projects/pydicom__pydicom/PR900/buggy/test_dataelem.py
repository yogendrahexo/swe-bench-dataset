# Copyright 2008-2018 pydicom authors. See LICENSE file for details.
"""Unit tests for the pydicom.dataelem module."""

# Many tests of DataElement class are implied in test_dataset also

import sys

import pytest

from pydicom.charset import default_encoding
from pydicom.dataelem import (
    DataElement,
    RawDataElement,
    DataElement_from_raw,
)
from pydicom.dataset import Dataset
from pydicom.multival import MultiValue
from pydicom.tag import Tag
from pydicom.uid import UID
from pydicom.valuerep import DSfloat


class TestDataElement(object):
    """Tests for dataelem.DataElement."""
    def setup(self):
        self.data_elementSH = DataElement((1, 2), "SH", "hello")
        self.data_elementIS = DataElement((1, 2), "IS", "42")
        self.data_elementDS = DataElement((1, 2), "DS", "42.00001")
        self.data_elementMulti = DataElement((1, 2), "DS",
                                             ['42.1', '42.2', '42.3'])
        self.data_elementCommand = DataElement(0x00000000, 'UL', 100)
        self.data_elementPrivate = DataElement(0x00090000, 'UL', 101)
        self.data_elementRetired = DataElement(0x00080010, 'SH', 102)

    def test_VM_1(self):
        """DataElement: return correct value multiplicity for VM > 1"""
        assert 3 == self.data_elementMulti.VM

    def test_VM_2(self):
        """DataElement: return correct value multiplicity for VM = 1"""
        assert 1 == self.data_elementIS.VM

    def test_DSFloat_conversion(self):
        """Test that strings are correctly converted if changing the value."""
        assert isinstance(self.data_elementDS.value, DSfloat)
        assert isinstance(self.data_elementMulti.value[0], DSfloat)
        assert DSfloat('42.1') == self.data_elementMulti.value[0]

        # multi-value append/insert
        self.data_elementMulti.value.append('42.4')
        assert isinstance(self.data_elementMulti.value[3], DSfloat)
        assert DSfloat('42.4') == self.data_elementMulti.value[3]

        self.data_elementMulti.value.insert(0, '42.0')
        assert isinstance(self.data_elementMulti.value[0], DSfloat)
        assert DSfloat('42.0') == self.data_elementMulti.value[0]

        # change single value of multi-value
        self.data_elementMulti.value[3] = '123.4'
        assert isinstance(self.data_elementMulti.value[3], DSfloat)
        assert DSfloat('123.4') == self.data_elementMulti.value[3]

    def test_backslash(self):
        """DataElement: String with '\\' sets multi-valued data_element."""
        data_element = DataElement((1, 2), "DS", r"42.1\42.2\42.3")
        assert 3 == data_element.VM

    def test_UID(self):
        """DataElement: setting or changing UID results in UID type."""
        ds = Dataset()
        ds.TransferSyntaxUID = "1.2.3"
        assert isinstance(ds.TransferSyntaxUID, UID)
        ds.TransferSyntaxUID += ".4.5.6"
        assert isinstance(ds.TransferSyntaxUID, UID)

    def test_keyword(self):
        """DataElement: return correct keyword"""
        assert 'CommandGroupLength' == self.data_elementCommand.keyword
        assert '' == self.data_elementPrivate.keyword

    def test_retired(self):
        """DataElement: return correct is_retired"""
        assert self.data_elementCommand.is_retired is False
        assert self.data_elementRetired.is_retired is True
        assert self.data_elementPrivate.is_retired is False

    def test_description_group_length(self):
        """Test DataElement.description for Group Length element"""
        elem = DataElement(0x00100000, 'LO', 12345)
        assert 'Group Length' == elem.description()

    def test_description_unknown_private(self):
        """Test DataElement.description with an unknown private element"""
        elem = DataElement(0x00110010, 'LO', 12345)
        elem.private_creator = 'TEST'
        assert 'Private tag data' == elem.description()
        elem = DataElement(0x00110F00, 'LO', 12345)
        assert elem.tag.is_private
        assert not hasattr(elem, 'private_creator')
        assert 'Private tag data' == elem.description()

    def test_description_unknown(self):
        """Test DataElement.description with an unknown element"""
        elem = DataElement(0x00000004, 'LO', 12345)
        assert '' == elem.description()

    def test_equality_standard_element(self):
        """DataElement: equality returns correct value for simple elements"""
        dd = DataElement(0x00100010, 'PN', 'ANON')
        assert dd == dd
        ee = DataElement(0x00100010, 'PN', 'ANON')
        assert dd == ee

        # Check value
        ee.value = 'ANAN'
        assert not dd == ee

        # Check tag
        ee = DataElement(0x00100011, 'PN', 'ANON')
        assert not dd == ee

        # Check VR
        ee = DataElement(0x00100010, 'SH', 'ANON')
        assert not dd == ee

        dd = DataElement(0x00080018, 'UI', '1.2.3.4')
        ee = DataElement(0x00080018, 'UI', '1.2.3.4')
        assert dd == ee

        ee = DataElement(0x00080018, 'PN', '1.2.3.4')
        assert not dd == ee

    def test_equality_private_element(self):
        """DataElement: equality returns correct value for private elements"""
        dd = DataElement(0x01110001, 'PN', 'ANON')
        assert dd == dd
        ee = DataElement(0x01110001, 'PN', 'ANON')
        assert dd == ee

        # Check value
        ee.value = 'ANAN'
        assert not dd == ee

        # Check tag
        ee = DataElement(0x01110002, 'PN', 'ANON')
        assert not dd == ee

        # Check VR
        ee = DataElement(0x01110001, 'SH', 'ANON')
        assert not dd == ee

    def test_equality_sequence_element(self):
        """DataElement: equality returns correct value for sequence elements"""
        dd = DataElement(0x300A00B0, 'SQ', [])
        assert dd == dd
        ee = DataElement(0x300A00B0, 'SQ', [])
        assert dd == ee

        # Check value
        e = Dataset()
        e.PatientName = 'ANON'
        ee.value = [e]
        assert not dd == ee

        # Check tag
        ee = DataElement(0x01110002, 'SQ', [])
        assert not dd == ee

        # Check VR
        ee = DataElement(0x300A00B0, 'SH', [])
        assert not dd == ee

        # Check with dataset
        dd = DataElement(0x300A00B0, 'SQ', [Dataset()])
        dd.value[0].PatientName = 'ANON'
        ee = DataElement(0x300A00B0, 'SQ', [Dataset()])
        ee.value[0].PatientName = 'ANON'
        assert dd == ee

        # Check uneven sequences
        dd.value.append(Dataset())
        dd.value[1].PatientName = 'ANON'
        assert not dd == ee

        ee.value.append(Dataset())
        ee.value[1].PatientName = 'ANON'
        assert dd == ee
        ee.value.append(Dataset())
        ee.value[2].PatientName = 'ANON'
        assert not dd == ee

    def test_equality_not_rlement(self):
        """DataElement: equality returns correct value when not same class"""
        dd = DataElement(0x00100010, 'PN', 'ANON')
        ee = {'0x00100010': 'ANON'}
        assert not dd == ee

    def test_equality_inheritance(self):
        """DataElement: equality returns correct value for subclasses"""

        class DataElementPlus(DataElement):
            pass

        dd = DataElement(0x00100010, 'PN', 'ANON')
        ee = DataElementPlus(0x00100010, 'PN', 'ANON')
        assert ee == ee
        assert dd == ee
        assert ee == dd

        ee = DataElementPlus(0x00100010, 'PN', 'ANONY')
        assert not dd == ee
        assert not ee == dd

    def test_equality_class_members(self):
        """Test equality is correct when ignored class members differ."""
        dd = DataElement(0x00100010, 'PN', 'ANON')
        dd.showVR = False
        dd.file_tell = 10
        dd.maxBytesToDisplay = 0
        dd.descripWidth = 0
        assert DataElement(0x00100010, 'PN', 'ANON') == dd

    def test_inequality_standard(self):
        """Test DataElement.__ne__ for standard element"""
        dd = DataElement(0x00100010, 'PN', 'ANON')
        assert not dd != dd
        assert DataElement(0x00100010, 'PN', 'ANONA') != dd

        # Check tag
        assert DataElement(0x00100011, 'PN', 'ANON') != dd

        # Check VR
        assert DataElement(0x00100010, 'SH', 'ANON') != dd

    def test_inequality_sequence(self):
        """Test DataElement.__ne__ for sequence element"""
        dd = DataElement(0x300A00B0, 'SQ', [])
        assert not dd != dd
        assert not DataElement(0x300A00B0, 'SQ', []) != dd
        ee = DataElement(0x300A00B0, 'SQ', [Dataset()])
        assert ee != dd

        # Check value
        dd.value = [Dataset()]
        dd[0].PatientName = 'ANON'
        ee[0].PatientName = 'ANON'
        assert not ee != dd
        ee[0].PatientName = 'ANONA'
        assert ee != dd

    def test_hash(self):
        """Test hash(DataElement) raises TypeError"""
        with pytest.raises(TypeError, match=r"unhashable"):
            hash(DataElement(0x00100010, 'PN', 'ANON'))

    def test_repeater_str(self):
        """Test a repeater group element displays the element name."""
        elem = DataElement(0x60023000, 'OB', b'\x00')
        assert 'Overlay Data' in elem.__str__()

    def test_str_no_vr(self):
        """Test DataElement.__str__ output with no VR"""
        elem = DataElement(0x00100010, 'PN', 'ANON')
        assert "(0010, 0010) Patient's Name" in str(elem)
        assert "PN: 'ANON'" in str(elem)
        elem.showVR = False
        assert "(0010, 0010) Patient's Name" in str(elem)
        assert 'PN' not in str(elem)

    def test_repr_seq(self):
        """Test DataElement.__repr__ with a sequence"""
        elem = DataElement(0x300A00B0, 'SQ', [Dataset()])
        elem[0].PatientID = '1234'
        assert repr(elem) == repr(elem.value)

    @pytest.mark.skipif(sys.version_info >= (3, ), reason='Python 2 behavior')
    def test_unicode(self):
        """Test unicode representation of the DataElement"""
        elem = DataElement(0x00100010, 'PN', u'ANON')
        # Make sure elem.value is actually unicode
        assert isinstance(elem.value, unicode)
        assert (
            u"(0010, 0010) Patient's Name                      PN: ANON"
        ) == unicode(elem)
        assert isinstance(unicode(elem), unicode)
        assert not isinstance(unicode(elem), str)
        # Make sure elem.value is still unicode
        assert isinstance(elem.value, unicode)

        # When value is not in compat.text_type
        elem = DataElement(0x00100010, 'LO', 12345)
        assert isinstance(unicode(elem), unicode)
        assert (
            u"(0010, 0010) Patient's Name                      LO: 12345"
        ) == unicode(elem)

    def test_getitem_raises(self):
        """Test DataElement.__getitem__ raise if value not indexable"""
        elem = DataElement(0x00100010, 'LO', 12345)
        with pytest.raises(TypeError):
            elem[0]

    def test_repval_large_elem(self):
        """Test DataElement.repval doesn't return a huge string for a large
        value"""
        elem = DataElement(0x00820003, 'UT', 'a'*1000)
        assert len(elem.repval) < 100

    def test_repval_large_vm(self):
        """Test DataElement.repval doesn't return a huge string for a large
        vm"""
        elem = DataElement(0x00080054, 'AE', 'a\\'*1000+'a')
        assert len(elem.repval) < 100

    def test_repval_strange_type(self):
        """Test DataElement.repval doesn't break with bad types"""
        elem = DataElement(0x00020001, 'OB', 0)
        assert len(elem.repval) < 100

    def test_private_tag_in_repeater_range(self):
        """Test that an unknown private tag (e.g. a tag not in the private
        dictionary) in the repeater range is not handled as a repeater tag
        if using Implicit Little Endian transfer syntax."""
        # regression test for #689
        ds = Dataset()
        ds[0x50f10010] = RawDataElement(
            Tag(0x50f10010), None, 8, b'FDMS 1.0', 0, True, True)
        ds[0x50f1100a] = RawDataElement(
            Tag(0x50f1100a), None, 6, b'ACC0.6', 0, True, True)
        private_creator_data_elem = ds[0x50f10010]
        assert 'Private Creator' == private_creator_data_elem.name
        assert 'LO' == private_creator_data_elem.VR

        private_data_elem = ds[0x50f1100a]
        assert '[FNC Parameters]' == private_data_elem.name
        assert 'UN' == private_data_elem.VR

    def test_private_repeater_tag(self):
        """Test that a known private tag in the repeater range is correctly
        handled using Implicit Little Endian transfer syntax."""
        ds = Dataset()
        ds[0x60210012] = RawDataElement(
            Tag(0x60210012), None, 12, b'PAPYRUS 3.0 ', 0, True, True)
        ds[0x60211200] = RawDataElement(
            Tag(0x60211200), None, 6, b'123456', 0, True, True)
        private_creator_data_elem = ds[0x60210012]
        assert 'Private Creator' == private_creator_data_elem.name
        assert 'LO' == private_creator_data_elem.VR

        private_data_elem = ds[0x60211200]
        assert '[Overlay ID]' == private_data_elem.name
        assert 'UN' == private_data_elem.VR

    def test_empty_text_values(self):
        """Test that assigning an empty value behaves as expected."""
        def check_empty_text_element(value):
            setattr(ds, tag_name, value)
            elem = ds[tag_name]
            assert bool(elem.value) is False

        text_vrs = {
            'AE': 'Receiver',
            'AS': 'PatientAge',
            'AT': 'OffendingElement',
            'CS': 'QualityControlSubject',
            'DA': 'PatientBirthDate',
            'DS': 'PatientWeight',
            'DT': 'AcquisitionDateTime',
            'IS': 'BeamNumber',
            'LO': 'DataSetSubtype',
            'LT': 'ExtendedCodeMeaning',
            'PN': 'PatientName',
            'SH': 'CodeValue',
            'ST': 'InstitutionAddress',
            'TM': 'StudyTime',
            'UC': 'LongCodeValue',
            'UI': 'SOPClassUID',
            'UR': 'CodingSchemeURL',
            'UT': 'StrainAdditionalInformation',
        }
        ds = Dataset()
        # set value to new element
        for tag_name in text_vrs.values():
            check_empty_text_element(None)
            del ds[tag_name]
            check_empty_text_element(b'')
            del ds[tag_name]
            check_empty_text_element(u'')
            del ds[tag_name]
            check_empty_text_element([])
            del ds[tag_name]

        # set value to existing element
        for tag_name in text_vrs.values():
            check_empty_text_element(None)
            check_empty_text_element(b'')
            check_empty_text_element(u'')
            check_empty_text_element([])
            check_empty_text_element(None)

    def test_empty_binary_values(self):
        """Test that assigning an empty value behaves as expected for
        non-text VRs."""
        def check_empty_binary_element(value):
            setattr(ds, tag_name, value)
            elem = ds[tag_name]
            assert bool(elem.value) is False

        non_text_vrs = {
            'SL': 'RationalNumeratorValue',
            'SS': 'SelectorSSValue',
            'UL': 'SimpleFrameList',
            'US': 'SourceAcquisitionBeamNumber',
            'FD': 'RealWorldValueLUTData',
            'FL': 'VectorAccuracy',
            'OB': 'FillPattern',
            'OD': 'DoubleFloatPixelData',
            'OF': 'UValueData',
            'OL': 'TrackPointIndexList',
            'OW': 'TrianglePointIndexList',
            'UN': 'SelectorUNValue',
        }
        ds = Dataset()
        # set value to new element
        for tag_name in non_text_vrs.values():
            check_empty_binary_element(None)
            del ds[tag_name]
            check_empty_binary_element([])
            del ds[tag_name]
            check_empty_binary_element(MultiValue(int, []))
            del ds[tag_name]

        # set value to existing element
        for tag_name in non_text_vrs.values():
            check_empty_binary_element(None)
            check_empty_binary_element([])
            check_empty_binary_element(MultiValue(int, []))
            check_empty_binary_element(None)


class TestRawDataElement(object):
    """Tests for dataelem.RawDataElement."""
    def test_key_error(self):
        """RawDataElement: conversion of unknown tag throws KeyError..."""
        # raw data element -> tag VR length value
        #                       value_tell is_implicit_VR is_little_endian'
        # Unknown (not in DICOM dict), non-private, non-group 0 for this test
        raw = RawDataElement(Tag(0x88880002), None, 4, 0x1111,
                             0, True, True)

        with pytest.raises(KeyError, match=r"\(8888, 0002\)"):
            DataElement_from_raw(raw)

    def test_valid_tag(self):
        """RawDataElement: conversion of known tag succeeds..."""
        raw = RawDataElement(Tag(0x00080020), 'DA', 8, b'20170101',
                             0, False, True)
        element = DataElement_from_raw(raw, default_encoding)
        assert 'Study Date' == element.name
        assert 'DA' == element.VR
        assert '20170101' == element.value

        raw = RawDataElement(Tag(0x00080000), None, 4, b'\x02\x00\x00\x00',
                             0, True, True)
        elem = DataElement_from_raw(raw, default_encoding)
        assert 'UL' == elem.VR

    def test_data_element_without_encoding(self):
        """RawDataElement: no encoding needed."""
        raw = RawDataElement(Tag(0x00104000), 'LT', 23,
                             b'comment\\comment2\\comment3',
                             0, False, True)
        element = DataElement_from_raw(raw)
        assert 'Patient Comments' == element.name

    def test_unknown_vr(self):
        """Test converting a raw element with unknown VR"""
        raw = RawDataElement(Tag(0x00080000), 'AA', 8, b'20170101',
                             0, False, True)
        with pytest.raises(NotImplementedError):
            DataElement_from_raw(raw, default_encoding)
