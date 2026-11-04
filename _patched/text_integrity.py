"""Content-free fingerprints for comparing the argument and application text.

No content, clipboard data or automatic draft reading is stored by this helper.
"""
import hashlib


def fingerprint(text):
    return {
        'characters': len(text),
        'utf16_units': len(text.encode('utf-16-le')) // 2,
        'ascii_double_quotes': text.count(chr(34)),
        'ascii_single_quotes': text.count(chr(39)),
        'line_feeds': text.count(chr(10)),
        'sha256_utf8': hashlib.sha256(text.encode('utf-8')).hexdigest(),
    }


def guidance():
    return dict(verification_method='not_performed',
                next_action='Read the target input field with approved UIA/OCR or ask the user to compare the draft character by character, including punctuation; do not send until confirmed. OCR alone does not prove exact text equality.')
