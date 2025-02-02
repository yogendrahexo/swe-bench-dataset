# Copyright 2008-2018 pydicom authors. See LICENSE file for details.
"""Functions for converting values of DICOM
   data elements to proper python types
"""

from io import BytesIO
from struct import (unpack, calcsize)

# don't import datetime_conversion directly
from pydicom import config
from pydicom import compat
from pydicom.compat import in_py2
from pydicom.charset import (default_encoding, text_VRs, decode_string)
from pydicom.config import logger
from pydicom.dataelem import empty_value_for_VR
from pydicom.filereader import read_sequence
from pydicom.multival import MultiValue
from pydicom.tag import (Tag, TupleTag)
import pydicom.uid
import pydicom.valuerep  # don't import DS directly as can be changed by config
from pydicom.valuerep import (MultiString, DA, DT, TM, TEXT_VR_DELIMS)

if not in_py2:
    from pydicom.valuerep import PersonName3 as PersonName
else:
    from pydicom.valuerep import PersonNameUnicode as PersonName


def convert_tag(byte_string, is_little_endian, offset=0):
    """Return a decoded :class:`BaseTag<pydicom.tag.BaseTag>` from the encoded
    `byte_string`.

    Parameters
    ----------
    byte_string : bytes
        The encoded tag.
    is_little_endian : bool
        ``True`` if the encoding is little endian, ``False`` otherwise.
    offset : int, optional
        The byte offset in `byte_string` to the start of the tag.

    Returns
    -------
    BaseTag
        The decoded tag.
    """
    if is_little_endian:
        struct_format = "<HH"
    else:
        struct_format = ">HH"
    return TupleTag(unpack(struct_format, byte_string[offset:offset + 4]))


def convert_AE_string(byte_string, is_little_endian, struct_format=None):
    """Return a decoded 'AE' value.

    Elements with VR of 'AE' have non-significant leading and trailing spaces.

    Parameters
    ----------
    byte_string : bytes or str
        The encoded 'AE' element value.
    is_little_endian : bool
        ``True`` if the value is encoded as little endian, ``False`` otherwise.
    struct_format : str, optional
        Not used.

    Returns
    -------
    str
        The decoded 'AE' value without non-significant spaces.
    """
    if not in_py2:
        byte_string = byte_string.decode(default_encoding)
    byte_string = byte_string.strip()
    return byte_string


def convert_ATvalue(byte_string, is_little_endian, struct_format=None):
    """Return a decoded 'AT' value.

    Parameters
    ----------
    byte_string : bytes or str
        The encoded 'AT' element value.
    is_little_endian : bool
        ``True`` if the value is encoded as little endian, ``False`` otherwise.
    struct_format : str, optional
        Not used.

    Returns
    -------
    BaseTag or list of BaseTag
        The decoded value(s).
    """
    length = len(byte_string)
    if length == 4:
        return convert_tag(byte_string, is_little_endian)

    # length > 4
    if length % 4 != 0:
        logger.warn("Expected length to be multiple of 4 for VR 'AT', "
                    "got length %d", length)
    return MultiValue(Tag, [
        convert_tag(byte_string, is_little_endian, offset=x)
        for x in range(0, length, 4)
    ])


def _DA_from_byte_string(byte_string):
    return DA(byte_string.rstrip())


def convert_DA_string(byte_string, is_little_endian, struct_format=None):
    """Return a decoded 'DA' value.

    Parameters
    ----------
    byte_string : bytes or str
        The encoded 'DA' element value.
    is_little_endian : bool
        ``True`` if the value is encoded as little endian, ``False`` otherwise.
    struct_format : str, optional
        Not used.

    Returns
    -------
    str or list of str or valuerep.DA or list of valuerep.DA
        If
        :attr:`~pydicom.config.datetime_conversion` is ``True`` then returns
        either :class:`~pydicom.valuerep.DA` or a :class:`list` of ``DA``,
        otherwise returns :class:`str` or ``list`` of ``str``.
    """
    if config.datetime_conversion:
        if not in_py2:
            byte_string = byte_string.decode(default_encoding)
        splitup = byte_string.split("\\")
        if len(splitup) == 1:
            return _DA_from_byte_string(splitup[0])
        else:
            return MultiValue(_DA_from_byte_string, splitup)
    else:
        return convert_string(byte_string, is_little_endian, struct_format)


def convert_DS_string(byte_string, is_little_endian, struct_format=None):
    """Return a decoded 'DS' value.

    Parameters
    ----------
    byte_string : bytes or str
        The encoded 'DS' element value.
    is_little_endian : bool
        ``True`` if the value is encoded as little endian, ``False`` otherwise.
    struct_format : str, optional
        Not used.

    Returns
    -------
    valuerep.DSfloat or valuerep.DSdecimal or list of DSfloat/DSdecimal
        If :attr:`~pydicom.config.use_DS_decimal` is ``True`` then returns
        :class:`~pydicom.valuerep.DSdecimal` or a :class:`list` of
        ``DSdecimal``, otherwise returns :class:`~pydicom.valuerep.DSfloat` or
        a ``list`` of ``DSfloat``.
    """
    if not in_py2:
        byte_string = byte_string.decode(default_encoding)
    # Below, go directly to DS class instance
    # rather than factory DS, but need to
    # ensure last string doesn't have
    # blank padding (use strip())
    return MultiString(byte_string.strip(), valtype=pydicom.valuerep.DSclass)


def _DT_from_byte_string(byte_string):
    byte_string = byte_string.rstrip()
    length = len(byte_string)
    if length < 4 or length > 26:
        logger.warn("Expected length between 4 and 26, got length %d", length)
    return DT(byte_string)


def convert_DT_string(byte_string, is_little_endian, struct_format=None):
    """Return a decoded 'DT' value.

    Parameters
    ----------
    byte_string : bytes or str
        The encoded 'DT' element value.
    is_little_endian : bool
        ``True`` if the value is encoded as little endian, ``False`` otherwise.
    struct_format : str, optional
        Not used.

    Returns
    -------
    str or list of str or valuerep.DT or list of DT
        if
        :attr:`~pydicom.config.datetime_conversion` is ``True`` then returns
        :class:`~pydicom.valuerep.DT` or a :class:`list` of ``DT``, otherwise
        returns :class:`str` or ``list`` of ``str``.
    """
    if config.datetime_conversion:
        if not in_py2:
            byte_string = byte_string.decode(default_encoding)
        splitup = byte_string.split("\\")
        if len(splitup) == 1:
            return _DT_from_byte_string(splitup[0])
        else:
            return MultiValue(_DT_from_byte_string, splitup)
    else:
        return convert_string(byte_string, is_little_endian, struct_format)


def convert_IS_string(byte_string, is_little_endian, struct_format=None):
    """Return a decoded 'IS' value.

    Parameters
    ----------
    byte_string : bytes or str
        The encoded 'IS' element value.
    is_little_endian : bool
        ``True`` if the value is encoded as little endian, ``False`` otherwise.
    struct_format : str, optional
        Not used.

    Returns
    -------
    valuerep.IS or list of IS
        The decoded value(s).
    """
    if not in_py2:
        byte_string = byte_string.decode(default_encoding)
    return MultiString(byte_string, valtype=pydicom.valuerep.IS)


def convert_numbers(byte_string, is_little_endian, struct_format):
    """Return a decoded numerical VR value.

    Given an encoded DICOM Element value, use `struct_format` and the
    endianness of the data to decode it.

    Parameters
    ----------
    byte_string : bytes or str
        The encoded numerical VR element value.
    is_little_endian : bool
        ``True`` if the value is encoded as little endian, ``False`` otherwise.
    struct_format : str
        The format of the numerical data encoded in `byte_string`. Should be a
        valid format for :func:`struct.unpack()` without the endianness.

    Returns
    -------
    str
        If there is no encoded data in `byte_string` then an empty string will
        be returned.
    value
        If `byte_string` encodes a single value then it will be returned.
    list
        If `byte_string` encodes multiple values then a list of the decoded
        values will be returned.
    """
    endianChar = '><' [is_little_endian]

    # "=" means use 'standard' size, needed on 64-bit systems.
    bytes_per_value = calcsize("=" + struct_format)
    length = len(byte_string)

    if length % bytes_per_value != 0:
        logger.warning("Expected length to be even multiple of number size")

    format_string = "%c%u%c" % (endianChar, length // bytes_per_value,
                                struct_format)

    value = unpack(format_string, byte_string)

    # if the number is empty, then return the empty
    # string rather than empty list
    if len(value) == 0:
        return ''
    elif len(value) == 1:
        return value[0]
    else:
        # convert from tuple to a list so can modify if need to
        return list(value)


def convert_OBvalue(byte_string, is_little_endian, struct_format=None):
    """Return encoded 'OB' value as :class:`bytes` or :class:`str`."""
    return byte_string


def convert_OWvalue(byte_string, is_little_endian, struct_format=None):
    """Return the encoded 'OW' value as :class:`bytes` or :class:`str`.

    No byte swapping will be performed.
    """
    # for now, Maybe later will have own routine
    return convert_OBvalue(byte_string, is_little_endian)


def convert_PN(byte_string, encodings=None):
    """Return a decoded 'PN' value.

    Parameters
    ----------
    byte_string : bytes or str
        The encoded 'IS' element value.
    encodings : list of str, optional
        A list of the character encoding schemes used to encode the 'PN' value.

    Returns
    -------
    valuerep.PersonName3 or list of PersonName3
        The decoded 'PN' value(s) if using Python 3.
    valuerep.PersonNameUnicode or list of PersonNameUnicode
        The decoded 'PN' value(s) if using Python 2.
    """
    def get_valtype(x):
        if not in_py2:
            return PersonName(x, encodings).decode()
        return PersonName(x, encodings)

    # XXX - We have to replicate MultiString functionality
    # here because we can't decode easily here since that
    # is performed in PersonNameUnicode
    if byte_string.endswith((b' ', b'\x00')):
        byte_string = byte_string[:-1]

    splitup = byte_string.split(b"\\")

    if len(splitup) == 1:
        return get_valtype(splitup[0])
    else:
        return MultiValue(get_valtype, splitup)


def convert_string(byte_string, is_little_endian, struct_format=None):
    """Return a decoded string VR value.

    String VRs are 'AS', 'CS' and optionally (depending on
    :ref:`pydicom.config <api_config>`) 'DA', 'DT', and 'TM'.

    Parameters
    ----------
    byte_string : bytes or str
        The encoded text VR element value.
    is_little_endian : bool
        ``True`` if the value is encoded as little endian, ``False`` otherwise.
    struct_format : str, optional
        Not used.

    Returns
    -------
    str or list of str
        The decoded value(s).
    """
    if not in_py2:
        byte_string = byte_string.decode(default_encoding)
    return MultiString(byte_string)


def convert_text(byte_string, encodings=None):
    """Return a decoded text VR value, ignoring backslashes.

    Text VRs are 'SH', 'LO' and 'UC'.

    Parameters
    ----------
    byte_string : bytes or str
        The encoded text VR element value.
    encodings : list of str, optional
        A list of the character encoding schemes used to encode the value.

    Returns
    -------
    unicode or list of unicode
        The decoded value(s) if in Python 2.
    str or list of str
        The decoded value(s) if in Python 3.
    """
    values = byte_string.split(b'\\')
    values = [convert_single_string(value, encodings) for value in values]
    if len(values) == 1:
        return values[0]
    else:
        return MultiValue(compat.text_type, values)


def convert_single_string(byte_string, encodings=None):
    """Return decoded text, ignoring backslashes.

    Parameters
    ----------
    byte_string : bytes or str
        The encoded text.
    encodings : list of str, optional
        A list of the character encoding schemes used to encode the text.

    Returns
    -------
    unicode or list of unicode
        The decoded text if in Python 2.
    str or list of str
        The decoded text if in Python 3.
    """
    encodings = encodings or [default_encoding]
    value = decode_string(byte_string, encodings, TEXT_VR_DELIMS)
    if value and value.endswith(' '):
        value = value[:-1]
    return value


def convert_SQ(byte_string, is_implicit_VR, is_little_endian,
               encoding=default_encoding, offset=0):
    """Return a decoded 'SQ' value.

    Parameters
    ----------
    byte_string : bytes or str
        The encoded 'SQ' element value.
    is_implicit_VR : bool
        ``True`` if the value is encoded as implicit VR, ``False`` otherwise.
    is_little_endian : bool
        ``True`` if the value is encoded as little endian, ``False`` otherwise.
    encoding : list of str, optional
        The character encoding scheme(s) used to encoded any text VR elements
        within the sequence value. ``'iso8859'`` is used by default.
    offset : int, optional
        The byte offset in `byte_string` to the start of the sequence value.

    Returns
    -------
    sequence.Sequence
        The decoded sequence.
    """
    fp = BytesIO(byte_string)
    seq = read_sequence(fp, is_implicit_VR, is_little_endian,
                        len(byte_string), encoding, offset)
    return seq


def _TM_from_byte_string(byte_string):
    byte_string = byte_string.rstrip()
    length = len(byte_string)
    if (length < 2 or length > 16) and length != 0:
        logger.warn("Expected length between 2 and 16, got length %d", length)
    return TM(byte_string)


def convert_TM_string(byte_string, is_little_endian, struct_format=None):
    """Return a decoded 'TM' value.

    Parameters
    ----------
    byte_string : bytes or str
        The encoded 'TM' element value.
    is_little_endian : bool
        ``True`` if the value is encoded as little endian, ``False`` otherwise.
    struct_format : str, optional
        Not used.

    Returns
    -------
    str or list of str or valuerep.TM or list of valuerep.TM
        If
        :attr:`~pydicom.config.datetime_conversion` is ``True`` then returns
        either :class:`~pydicom.valuerep.TM` or a :class:`list` of ``TM``,
        otherwise returns :class:`str` or ``list`` of ``str``.
    """
    if config.datetime_conversion:
        if not in_py2:
            byte_string = byte_string.decode(default_encoding)
        splitup = byte_string.split("\\")
        if len(splitup) == 1:
            return _TM_from_byte_string(splitup[0])
        else:
            return MultiValue(_TM_from_byte_string, splitup)
    else:
        return convert_string(byte_string, is_little_endian, struct_format)


def convert_UI(byte_string, is_little_endian, struct_format=None):
    """Return a decoded 'UI' value.

    Elements with VR of 'UI' may have a non-significant trailing null ``0x00``.

    Parameters
    ----------
    byte_string : bytes or str
        The encoded 'UI' element value.
    is_little_endian : bool
        ``True`` if the value is encoded as little endian, ``False`` otherwise.
    struct_format : str, optional
        Not used.

    Returns
    -------
    uid.UID or list of uid.UID
        The decoded 'UI' element value without a trailing null.
    """
    # Strip off 0-byte padding for even length (if there)
    if not in_py2:
        byte_string = byte_string.decode(default_encoding)
    if byte_string and byte_string.endswith('\0'):
        byte_string = byte_string[:-1]
    return MultiString(byte_string, pydicom.uid.UID)


def convert_UN(byte_string, is_little_endian, struct_format=None):
    """Return encoded 'UN' value as :class:`bytes` or :class:`str`."""
    return byte_string


def convert_UR_string(byte_string, is_little_endian, struct_format=None):
    """Return encoded 'UR' value.

    Elements with VR of 'UR' may not be multi-valued and trailing spaces are
    non-significant.

    Parameters
    ----------
    byte_string : bytes or str
        The encoded 'UR' element value.
    is_little_endian : bool
        ``True`` if the value is encoded as little endian, ``False`` otherwise.
    struct_format : str, optional
        Not used.

    Returns
    -------
    bytes or str
        The encoded 'UR' element value without any trailing spaces.
    """
    if not in_py2:
        byte_string = byte_string.decode(default_encoding)
    byte_string = byte_string.rstrip()
    return byte_string


def convert_value(VR, raw_data_element, encodings=None):
    """Return encoded element value using the appropriate decoder.

    Parameters
    ----------
    raw_data_element : bytes or str
        The encoded element value.
    encodings : list of str, optional
        A list of the character encoding schemes used to encode any text
        elements.

    Returns
    -------
    type or list of type
        The element value decoded using the appropriate decoder.
    """
    if VR not in converters:
        # `VR` characters are in the ascii alphabet ranges 65 - 90, 97 - 122
        char_range = list(range(65, 91)) + list(range(97, 123))
        # If the VR characters are outside that range then print hex values
        if ord(VR[0]) not in char_range or ord(VR[1]) not in char_range:
            VR = ' '.join(['0x{:02x}'.format(ord(ch)) for ch in VR])
        message = "Unknown Value Representation '{}'".format(VR)
        raise NotImplementedError(message)

    if raw_data_element.length == 0:
        return empty_value_for_VR(VR)

    # Look up the function to convert that VR
    # Dispatch two cases: a plain converter,
    # or a number one which needs a format string
    if isinstance(converters[VR], tuple):
        converter, num_format = converters[VR]
    else:
        converter = converters[VR]
        num_format = None

    # Ensure that encodings is a list
    encodings = encodings or [default_encoding]
    if isinstance(encodings, compat.string_types):
        encodings = [encodings]

    byte_string = raw_data_element.value
    is_little_endian = raw_data_element.is_little_endian
    is_implicit_VR = raw_data_element.is_implicit_VR

    # Not only two cases. Also need extra info if is a raw sequence
    # Pass all encodings to the converter if needed
    try:
        if VR in text_VRs or VR == 'PN':
            value = converter(byte_string,
                              encodings=encodings)
        elif VR != "SQ":
            value = converter(byte_string,
                              is_little_endian,
                              num_format)
        else:
            value = convert_SQ(byte_string,
                               is_implicit_VR,
                               is_little_endian,
                               encodings,
                               raw_data_element.value_tell)
    except ValueError:
        if config.enforce_valid_values:
            # The user really wants an exception here
            raise
        logger.debug('unable to translate tag %s with VR %s'
                     % (raw_data_element.tag, VR))

        for vr in convert_retry_VR_order:
            if vr == VR:
                continue
            try:
                value = convert_value(vr, raw_data_element, encodings)
                logger.debug('converted value for tag %s with VR %s'
                             % (raw_data_element.tag, vr))
                break
            except Exception:
                pass
        else:
            logger.debug('Could not convert value for tag %s with any VR '
                         'in the convert_retry_VR_order list'
                         % raw_data_element.tag)
            value = raw_data_element.value
    return value


convert_retry_VR_order = [
    'SH', 'UL', 'SL', 'US', 'SS', 'FL', 'FD', 'OF', 'OB', 'UI', 'DA', 'TM',
    'PN', 'IS', 'DS', 'LT', 'SQ', 'UN', 'AT', 'OW', 'DT', 'UT', ]
# converters map a VR to the function
# to read the value(s). for convert_numbers,
# the converter maps to a tuple
# (function, struct_format)
# (struct_format in python struct module style)
converters = {
    'UL': (convert_numbers, 'L'),
    'SL': (convert_numbers, 'l'),
    'US': (convert_numbers, 'H'),
    'SS': (convert_numbers, 'h'),
    'FL': (convert_numbers, 'f'),
    'FD': (convert_numbers, 'd'),
    'OF': (convert_numbers, 'f'),
    'OB': convert_OBvalue,
    'OD': convert_OBvalue,
    'OL': convert_OBvalue,
    'UI': convert_UI,
    'SH': convert_text,
    'DA': convert_DA_string,
    'TM': convert_TM_string,
    'CS': convert_string,
    'PN': convert_PN,
    'LO': convert_text,
    'IS': convert_IS_string,
    'DS': convert_DS_string,
    'AE': convert_AE_string,
    'AS': convert_string,
    'LT': convert_single_string,
    'SQ': convert_SQ,
    'UC': convert_text,
    'UN': convert_UN,
    'UR': convert_UR_string,
    'AT': convert_ATvalue,
    'ST': convert_single_string,
    'OW': convert_OWvalue,
    'OW/OB': convert_OBvalue,  # note OW/OB depends on other items,
    'OB/OW': convert_OBvalue,  # which we don't know at read time
    'OW or OB': convert_OBvalue,
    'OB or OW': convert_OBvalue,
    'US or SS': convert_OWvalue,
    'US or OW': convert_OWvalue,
    'US or SS or OW': convert_OWvalue,
    'US\\US or SS\\US': convert_OWvalue,
    'DT': convert_DT_string,
    'UT': convert_single_string,
}
