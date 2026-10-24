"""TuxGuitar .tg file formats (IO-01, IO-02): the legacy binary formats 1.0-1.5 read through tgimport's validator.

The legacy fixtures below were written by the installed TuxGuitar 2.1.0 compat writers (v10..v15) from
rich_xml(), our own current-format fixture; rich.v10.current is TuxGuitar's own 2.0 rewrite of the 1.0 file
(scratch/tg-format/oracle.py). They stay inline so the tests need no TuxGuitar.
"""
import base64
import copy
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

from tests import test_gpimport
from vulturetracker import tglegacy, tgimport

# Its helpers only: a TestCase class bound in this module would rerun its tests here.
semantics, archive = test_gpimport.TestTgInterchange.semantics, test_gpimport.TestTgInterchange.archive
Q = tgimport.QUARTER
FIXTURES = {
    'rich.v10': (
        'GwBUAHUAeABHAHUAaQB0AGEAcgAgAEYAaQBsAGUAIABGAG8AcgBtAGEAdAAgAC0AIAAxAC4AMAsAUgBpAGMAaAAgAGwAZQBn'
        'AGEAYwB5BgBBAHIAdABpAHMAdAUAQQBsAGIAdQBtBgBBAHUAdABoAG8AcgAEIwQABABkBQBJAG4AdAByAG/ICgpEAlgAAQEB'
        'EwMABAB4AgIBBABMAGUAYQBkAAABHX9AAAAAAAMNAQABAQACAQADCAAGUAYCAEUAbQAAAAACAgAVDAMCZAAACAACAl8DBQB2'
        'AGUAcgBzAGUHBAgDAggCA18FAAQDBQAFAwYABAwHAUAAIAABAQAHAQQEDAEAAAQCAwcACAQFAgAAEAcQBwIEBAQDAAAgEAYA'
        'EAQFAQDAAAAGAAECBQEABQQHAgQAAgMADAYKDAwFBAcCABABAwAABgQMBAQNCQM8AAUABAkEAAhABkA7NzItKBgKFB4AAQAA'
        'AAgAbABhACAAbABhACAAbABhAAUARAByAHUAbQBzAAkJAH9AAAAAAAMFASQBCCoCRgUJJgFfCCoCRgUJJAFfCCoCRgQJJgFf'
        'CCoCRgEAAAUBJAEIKgJGBQkmAV8IKgJGBQkkAV8IKgJGBAkmAV8IKgJGAAUBJAEIKgJGBQkmAV8IKgJGBQkkAV8IKgJGBAkm'
        'AV8IKgJGAAUBJAEIKgJGBQkmAV8IKgJGBAkkAV8IKgJGBgAAAAAAABgBAQE='
    ),
    'rich.v11': (
        'GwBUAHUAeABHAHUAaQB0AGEAcgAgAEYAaQBsAGUAIABGAG8AcgBtAGEAdAAgAC0AIAAxAC4AMQsAUgBpAGMAaAAgAGwAZQBn'
        'AGEAYwB5BgBBAHIAdABpAHMAdAUAQQBsAGIAdQBtBgBBAHUAdABoAG8AcgAEIwQABABkBQBJAG4AdAByAG/ICgpEAlgAAQEB'
        'EwMABAB4AgIEBABMAGUAYQBkAAEdf0AAAAAAA/cBAQABAQACAAADCwACCAAGUP8IBgIARQBtAAAAAAICABkMAwJkAAAIAAIC'
        'XwMFAHYAZQByAHMAZfEDBAgDAggCA18AMQEABAMRAAUDMAMABAwHAUAAIAABAQAxAwEEBAwBAAAEAgMRAAgEBQIAABAHEBEC'
        'BAQEAwAAIBAQABAEBQEAwAAAMAMAAQIFAQAxAQQHAgQAAgMADAYKDAwRBAcCABABAwAABgQMBBANCQM8AAUABAkEAAhABkA7'
        'NzItKBgKFB4AAQAAAAgAbABhACAAbABhACAAbABhAAUARAByAHUAbQBzCQkAf0AAAAAAAzEBASQBCCoCRhEJJgFfCCoCRhEJ'
        'JAFfCCoCRhAJJgFfCCoCRgEAADEBASQBCCoCRhEJJgFfCCoCRhEJJAFfCCoCRhAJJgFfCCoCRgAxAQEkAQgqAkYRCSYBXwgq'
        'AkYRCSQBXwgqAkYQCSYBXwgqAkYAMQEBJAEIKgJGEQkmAV8IKgJGEAkkAV8IKgJGBgAAAAAAABgBAQE='
    ),
    'rich.v12': (
        'GwBUAHUAeABHAHUAaQB0AGEAcgAgAEYAaQBsAGUAIABGAG8AcgBtAGEAdAAgAC0AIAAxAC4AMgsAUgBpAGMAaAAgAGwAZQBn'
        'AGEAYwB5BgBBAHIAdABpAHMAdAUAQQBsAGIAdQBtBgBBAHUAdABoAG8AcgQAMgAwADIANgkAKABjACkAIABvAHcAbgBlAHIG'
        'AFcAcgBpAHQAZQByCwBUAHIAYQBuAHMAYwByAGkAYgBlAHIAAAARAGwAaQBuAGUAIABvAG4AZQAKAGwAaQBuAGUAIAB0AHcA'
        'bwAEIwQABABkBQBJAG4AdAByAG/ICgpEAlgAAQEBEwMABAB4AgIEBABMAGUAYQBkAAEdf0AAAAAAA/cBAQABAQACAAADCwAC'
        'CAAGUP8IBgIARQBtAAAAAAICABkMAwJkAAAIAAICXwMFAHYAZQByAHMAZfEDBAgDAggCA18AMQEABAMRAAUDMAMABAwHAUAA'
        'IAABAQAxAwEEBAwBAAAEAgMRAAgEBQIAABAHEBECBAQEAwgAIBAQABAEBQEAwAAAMAMAAQIFAQAxAQQHAgQAAgMADAYKDAwR'
        'BAcCABABAwAABgQMBBANCQM8AAUABAkEAAhABkA7NzItKBgKFB4AAQAAAAgAbABhACAAbABhACAAbABhAAUARAByAHUAbQBz'
        'CQkAf0AAAAAAAzEBASQBCCoCRhEJJgFfCCoCRhEJJAFfCCoCRhAJJgFfCCoCRgEAADEBASQBCCoCRhEJJgFfCCoCRhEJJAFf'
        'CCoCRhAJJgFfCCoCRgAxAQEkAQgqAkYRCSYBXwgqAkYRCSQBXwgqAkYQCSYBXwgqAkYAMQEBJAEIKgJGEQkmAV8IKgJGEAkk'
        'AV8IKgJGBgAAAAAAABgBAQE='
    ),
    'rich.v13': (
        'GwBUAHUAeABHAHUAaQB0AGEAcgAgAEYAaQBsAGUAIABGAG8AcgBtAGEAdAAgAC0AIAAxAC4AMwsAUgBpAGMAaAAgAGwAZQBn'
        'AGEAYwB5BgBBAHIAdABpAHMAdAUAQQBsAGIAdQBtBgBBAHUAdABoAG8AcgQAMgAwADIANgkAKABjACkAIABvAHcAbgBlAHIG'
        'AFcAcgBpAHQAZQByCwBUAHIAYQBuAHMAYwByAGkAYgBlAHIAAAARAGwAaQBuAGUAIABvAG4AZQAKAGwAaQBuAGUAIAB0AHcA'
        'bwIAAQAdf0AAAAAABABMAGUAYQBkAAAAAoAAf0AAAAAAAwBLAGkAdAACDABnAG0ALQBjAGgAYQBuAG4AZQBsAC0AMQAAAAEA'
        'OQwAZwBtAC0AYwBoAGEAbgBuAGUAbAAtADIAAAABADkABCMEAAQAZAUASQBuAHQAcgBvyAoKRAJYAAEBARMDAAQAeAICBAQA'
        'TABlAGEAZAABA/cBAQABAQACAAADCwACCAAGUP8IBgIARQBtAAAAAAICABkMAwJkAAAIAAICXwMFAHYAZQByAHMAZfEDBAgD'
        'AggCA18AMQEABAMRAAUDMAMABAwHAUAAIAABAQAxAwEEBAwBAAAEAgMRAAgEBQIAABAHEBECBAQEAwgAIBAQABAEBQEAwAAA'
        'MAMAAQIFAQAxAQQHAgQAAgMADAYKDAwRBAcCABABAwAABgQMBBANCQM8AAUABAkEAAhABkA7NzItKBgKFB4AAQAAAAgAbABh'
        'ACAAbABhACAAbABhAAUARAByAHUAbQBzAAIDMQEBJAEIKgJGEQkmAV8IKgJGEQkkAV8IKgJGEAkmAV8IKgJGAQAAMQEBJAEI'
        'KgJGEQkmAV8IKgJGEQkkAV8IKgJGEAkmAV8IKgJGADEBASQBCCoCRhEJJgFfCCoCRhEJJAFfCCoCRhAJJgFfCCoCRgAxAQEk'
        'AQgqAkYRCSYBXwgqAkYQCSQBXwgqAkYGAAAAAAAAGAEBAQ=='
    ),
    'rich.v15': (
        'GwBUAHUAeABHAHUAaQB0AGEAcgAgAEYAaQBsAGUAIABGAG8AcgBtAGEAdAAgAC0AIAAxAC4ANQsAUgBpAGMAaAAgAGwAZQBn'
        'AGEAYwB5BgBBAHIAdABpAHMAdAUAQQBsAGIAdQBtBgBBAHUAdABoAG8AcgQAMgAwADIANgkAKABjACkAIABvAHcAbgBlAHIG'
        'AFcAcgBpAHQAZQByCwBUAHIAYQBuAHMAYwByAGkAYgBlAHIAAAARAGwAaQBuAGUAIABvAG4AZQAKAGwAaQBuAGUAIAB0AHcA'
        'bwIAAQAdf0AAAAAABABMAGUAYQBkAAAAAoAAf0AAAAAAAwBLAGkAdAACDABnAG0ALQBjAGgAYQBuAG4AZQBsAC0AMQAAAAEA'
        'OQwAZwBtAC0AYwBoAGEAbgBuAGUAbAAtADIAAAABADkABCMEAAQAZAUASQBuAHQAcgBvyAoKRAJYAAEBARMDAAQAeAICBAQA'
        'TABlAGEAZAABA/cBAQABAQACAAADCwACCAAGUP8IBgIARQBtAAAAAAICABkMAwJkAAAIAAICXwMFAHYAZQByAHMAZfEDBAgD'
        'AggCA18AMQEABAMRAAUDMAMABAwHAUAAIAABAQAxAwEEBAwBAAAEAgMRAAgEBQIAABAHEBECBAQEAwgAIBAQABAEBQEAwAAA'
        'MAMAAQIFAQAxAQQHAgQAAgMADAYKDAwRBAcCABABAwAABgQMBBANCQM8AAUABAkEAAhABkA7NzItKBgKFB4AAQAAAAgAbABh'
        'ACAAbABhACAAbABhAAUARAByAHUAbQBzAAIDMQEBJAEIKgJGEQkmAV8IKgJGEQkkAV8IKgJGEAkmAV8IKgJGAQAAMQEBJAEI'
        'KgJGEQkmAV8IKgJGEQkkAV8IKgJGEAkmAV8IKgJGADEBASQBCCoCRhEJJgFfCCoCRhEJJAFfCCoCRhAJJgFfCCoCRgAxAQEk'
        'AQgqAkYRCSYBXwgqAkYQCSQBXwgqAkYGAAAAAAAAGAEBAQ=='
    ),
    'rich.v10.current': (
        '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'
    ),
    'seed13.v15': (
        'GwBUAHUAeABHAHUAaQB0AGEAcgAgAEYAaQBsAGUAIABGAG8AcgBtAGEAdAAgAC0AIAAxAC4ANRkATgBhAHQAaQB2AGUAIABp'
        'AG4AdABlAHIAbwBwAGUAcgBhAGIAaQBsAGkAdAB5ACAAZgAAAAAAAAAAAAAtAFMAbwB1AHIAYwBlACAAdABpAHQAbABlADoA'
        'IABOAGEAdABpAHYAZQAgAGkAbgB0AGUAcgBvAHAAZQByAGEAYgBpAGwAaQB0AHkAIABmAGkAeAB0AHUAcgBlAQABABl/QAAA'
        'AAAGAEcAdQBpAHQAYQByAAAAASMEAAQAiQwAVgBlAHIAcwBlACAAJgAgAGMAYQBmAOkXLUMBAAYARwB1AGkAdABhAHIAAQM5'
        'AwQIDQgIAAFPFABMAGkAdABlAHIAYQBsACAAPAB0AGEAZwA+ACAAJgAgAGMAYQBmAOkxAQABATEAMQEEAwEABAARBAQBAAIA'
        'EQAAAREAAQERAAIBEQADAREABAERAAABEQABARAAAgEBAAFAGAAAAA=='
    ),
    'seed13.v10': (
        'GwBUAHUAeABHAHUAaQB0AGEAcgAgAEYAaQBsAGUAIABGAG8AcgBtAGEAdAAgAC0AIAAxAC4AMBkATgBhAHQAaQB2AGUAIABp'
        'AG4AdABlAHIAbwBwAGUAcgBhAGIAaQBsAGkAdAB5ACAAZgAAAAABIwQABACJDABWAGUAcgBzAGUAIAAmACAAYwBhAGYA6Rct'
        'QwEABgBHAHUAaQB0AGEAcgAAARl/QAAAAAADFwQIDQgIAAFPFABMAGkAdABlAHIAYQBsACAAPAB0AGEAZwA+ACAAJgAgAGMA'
        'YQBmAOkFAAEBAQUEAwEABAAFBAQBAAIABQAAAQUAAQEFAAIBBQADAQUABAEFAAABBQABAQQAAgEBAAQrJiEcGAAAAA=='
    ),
    'rich-ours.v10.tg-read': (
        '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'
    ),
    'rich-ours.v15.tg-read': (
        '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'
        'SwUGAAAAAAIAAgByAAAAlQYAAAAA'
    ),
    'old.v07.tg-read': (
        'UEsDBBQACAgIALV+VF0AAAAAAAAAAAAAAAALAAAAdmVyc2lvbi50eHQLKa1wL80sSSyKT8vMSY1Pyy/KTSxRMNIzAABQSwcI'
        't3pUuRsAAAAZAAAAUEsDBBQACAgIALV+VF0AAAAAAAAAAAAAAAALAAAAY29udGVudC54bWztWW1v2zYQ/iuCvieSaMmWAVpF'
        'uiHZgG4tmmzfaelsc6FIg6Lc5N/3qBdbcpQsbZNY6AYI5t1JRx2fe+50gOm7u1w4O9AFV3LhBue+64BMVcbleuH+dXN5FrtO'
        'YZjMmFASFq5U7ruE3pR3VyU3TF9yAahe/V3v4OTsH6UXLnGdnEsrBa6jYcfr7X3Xsw9fK7lOqGQ5JB9F5hi2pF6lUaYNL0xy'
        'US3Ua1TKxLLMkwv7i8ZKoaw0G6WTi2pBa63SjBnAl6Rqe6/5emNQ/qK5AY2C0UwWqebLSktVnoM0RRXSLxsmJYiE8iwJqIe/'
        'dMnkbeJTr1rpVqu1ZnlCIuq1Mt0pUWLYAZlRr5HRTTCZQjINrWst0xRjKwu7WyNRBAX00loaiW43rABtLY2E8UKuhLKmVqxR'
        'WyHq5wXbwXkGK1YKc2bNTtDCuD/PJ4ZxAp7euYX7hbvOz9L6xhnmZcdECfuk/KsH6Xt4HdD6+JEOfgGJjxH0RwAgl4XRpU3/'
        'eYbrLTffCd78m8GbPwTvD2BFqeE3YFkVNc/hmq8lM2h0MpAKa4kZW02h60gMW7eaJTXkW5UEvj1jJdrNj3Z8k1fcaJbeYgO4'
        'u9RgsAXM3QbsD/hIC26Dx+9VlR0ULEahtPN+4U6wAV2hNy6fsXu0HcNobEgVJfbKwRzNh83RsNkfNIfDT4dHT3/AtpI6K61y'
        '29u8DrZ4CAGrBIm2FICHswpFHuxxtjTs6ej7HpixpQEpL+AaG6pJSBzjVVVJx4qlwm0hZCVmxnbahk4hopzxusHe3G8Buzfy'
        'r6gar81y0YTptY6YFGUAe7quWny3D+B3QKiUG6TuPMJ9d3xpaWC9rc+R54HS9QuaAKvFQZrYbbDIwH2RoNvtvRazQeyi2RSv'
        'YezamFZMFC8c1EnPHE9DvJ7Ll/ixMCb7MMhTfJnss066fIl93HfD8IuqD3QZBTzzqY/X28MTHsEzlhIJ/GjmR4/UyGsCEj3g'
        'SyF4BiOjSxBEkyAib99+e/AEgcVnCRI/jVvFpXG2quCmGaJ7c9jx7WmHgQO3A9K/79UvOVEKvM7XsycOZSYM8Xp2JZMfz4zh'
        'kP2JtgaCRzM1ltImfhD7wbNL+0cROjBp0kVkZqmb4cxnoTtddXep5TXT6X5MbSbTX3H2Lx6OpuQ7RtPhofKNrD/vUDqZHk2l'
        '3qMkDMkRC8dSlk8Npa+KXfwQu1EA8m0T6+uSaRSAnGzoGANFXnEG+L8P9cCbkfmMnKKJj4BlLzEw/Qc6EZn404l/it48Ao4M'
        'j4xe+4eF1//X4ytQSwcI4JAPCsYDAAA7GQAAUEsBAhQAFAAICAgAtX5UXbd6VLkbAAAAGQAAAAsAAAAAAAAAAAAAAAAAAAAA'
        'AHZlcnNpb24udHh0UEsBAhQAFAAICAgAtX5UXeCQDwrGAwAAOxkAAAsAAAAAAAAAAAAAAAAAVAAAAGNvbnRlbnQueG1sUEsF'
        'BgAAAAACAAIAcgAAAFMEAAAAAA=='
    ),
    'old.v08.tg-read': (
        'UEsDBBQACAgIALV+VF0AAAAAAAAAAAAAAAALAAAAdmVyc2lvbi50eHQLKa1wL80sSSyKT8vMSY1Pyy/KTSxRMNIzAABQSwcI'
        't3pUuRsAAAAZAAAAUEsDBBQACAgIALV+VF0AAAAAAAAAAAAAAAALAAAAY29udGVudC54bWztWW1v2zYQ/iuCvieSaMkvAK0i'
        '7ZCsQLcWS7bvtHS2OVOkQFFe8u931IstOUqXtkksbAME8+4kUsfnnjueIfruPhPOHnTBlVy6waXvOiATlXK5Wbq/311fzF2n'
        'MEymTCgJS1cq911M78r7m5Ibpq+5AFRv/qhXcDL2p9JLl7hOxqWVAtfRsOf18r7r2YdvldzEVLIM4s8idQxbUa/SKNOGFya+'
        'qgbqNSplYlVm8ZX9RWOlUFaardLxVTWgtVZpygzgSxKVP2i+2RqU/9LcgEbBaCaLRPNVpSUqy0CaonLpw5ZJCSKmPI0D6uEv'
        'XTG5i33qVSPNtdpolsUkol4r070SJbodkBn1GhmnCSYTiKehnVrLNEHfysKu1kgUQQG9spZGovmWFaCtpZHQX8iUUNbUijVq'
        'a0T9smB7uExhzUphLqzZCVoYD/v5wtBPwN07O3hYupvsIqlvXGBc9kyUcAjKP84g/RleB7Q+fqSDX0Dmpwj6IwCQy8Lo0ob/'
        'MsVxx813grf4ZvAWj8H7BVhRavgZWFp5zTO45RvJDBqdFKTCXGLGZlPoOhLd1q1mSQ1ZruLAt3usREQmB2Y+5yDxdsb0Dv15'
        'j5mIqX1TD79hhvq+G3+URivq1c9UXp248jK+kVPfPghVgM2zrorR4rkAcw2ICtjc3dqwHW2D/t1pluyw7NxfazC4rYXbhPgT'
        'PtKGtInCxyq3jwqWAKEqbCY1NqTGJmjrFL4dK5Ul4kE5mqPFsDkaNvuD5nD46fDk6U9YzBJnrVVmK6rXCQxuQsA6RnqvBODm'
        'rEKRfYcgWfL3dJz7HkG3CQkJL+AWy7iJyXyOV5WbHSsmKLfpl5YYVlvfGxKHiHLK67J+95ADnhnI+qIq95YiReOm107EoCgD'
        'eJLo6mDpVh88fYRKuMGEWUS47p6vLIfsbDvnZOYxkeoXNA5Wg4Mcs8tgaoP7Ik63y3stZoPYRbMpXsPYtT6tmShe2Kmz7nk+'
        'DfF6Ll/mT7kxObhBvsaXySHqpMuXOdYwumV4jusjXUYBz2Lq4/X28IQn8IwlRQI/mvnREznymoBEj/hSCJ7CyOgSBNEkiMjb'
        'l98ePEFg8VmBxKMxV1waJ1cFN03r3uv+Tm9POwwcuB2Q/n2vfsmZQuB1Ts+eOBSZMMTr2ZlMfjwyhkP6K9oaCJ6M1FhSm/jB'
        '3A+endo/itCRSZMuIjNL3RR7Pgvd+bK7Sy2v6U4PbWrTmf6E/ziKx60p+Y7WdLipfCPrv7cpnUxPulLvSRKG5ISFY0nLrzWl'
        'r4rd/DF2owDk2zrW1yXTKAA5W9MxBoq8Yg/wfx3qgTcjixk5RxEfActeomH6D1QiMvGnE/8ctXkEHBluGb32M4nX/9byN1BL'
        'BwgpqJGeAQQAALEZAABQSwECFAAUAAgICAC1flRdt3pUuRsAAAAZAAAACwAAAAAAAAAAAAAAAAAAAAAAdmVyc2lvbi50eHRQ'
        'SwECFAAUAAgICAC1flRdKaiRngEEAACxGQAACwAAAAAAAAAAAAAAAABUAAAAY29udGVudC54bWxQSwUGAAAAAAIAAgByAAAA'
        'jgQAAAAA'
    ),
    'old.v09.tg-read': (
        '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'
    ),
    'drumgap.tg-read': (
        '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'
    ),
}


def fixture(name):
    return base64.b64decode(''.join(FIXTURES[name]))


def rich_xml():
    """Two tracks (guitar, drums), two voices, stroke, chord, text, grace, triplets, dots, harmonic, trill,
    tremolo picking, let ring, tapping, tie, tremolo bar, bend, fade in, accents, repeats, endings, swing,
    marker, meter/tempo change, lyrics, credits."""
    def beat(at, voices, extra=''):
        out = f'<TGBeat><preciseStart>{Q + int(Fraction(at) * Q)}</preciseStart>{extra}'
        return out + ''.join(voices + ['<voice empty="true"><duration value="4"/></voice>'] * (2 - len(voices))) + '</TGBeat>'

    def voice(duration, notes='', attrs=''):
        return f'<voice{attrs}>{duration}{notes}</voice>' if notes else f'<voice empty="false"{attrs}>{duration}</voice>'

    def d(value, dotted=None, tuplet=None):
        a = f' dotted="{dotted}"' if dotted else ''
        t = f'<divisionType enters="{tuplet[0]}" times="{tuplet[1]}"/>' if tuplet else ''
        return f'<duration value="{value}"{a}>{t}</duration>'

    def n(string, fret, vel=95, inner='', tied=False):
        return f'<note string="{string}" value="{fret}" velocity="{vel}"{" tiedNote=\"true\"" if tied else ""}>{inner}</note>'

    third = Fraction(1, 3)
    m1 = [beat(0, [voice(d(4), n(1, 0) + n(2, 0) + n(3, 0)), voice(d(2), n(6, 0, 80), ' direction="down"')],
               '<stroke direction="down" value="8"/><chord><name>Em</name><firstFret>0</firstFret>'
               + '<string>0</string>' * 3 + '<string>2</string>' * 2 + '<string>0</string></chord>'),
          beat(1, [voice(d(4), n(2, 3, 100, '<grace fret="2" duration="32" dynamic="95" transition="hammer" '
                                           'onBeat="false" dead="false"/>'))], '<text>verse</text>'),
          beat(2, [voice(d(8, tuplet=(3, 2)), n(3, 2)), voice(d(2))]),
          beat(2 + third, [voice(d(8, tuplet=(3, 2)), n(3, 4))]),
          beat(2 + 2 * third, [voice(d(8, tuplet=(3, 2)), n(3, 5))]),
          beat(3, [voice(d(4), n(1, 7, 64, '<palmMute/>'))])]
    m2 = [beat(4, [voice(d(4, 'dotted'), n(1, 12, 95, '<harmonic type="A.H" data="3"/>'))], '<pickStroke>up</pickStroke>'),
          beat(Fraction(11, 2), [voice(d(8), n(2, 5, 95, '<trill fret="7" duration="16"/>'))]),
          beat(6, [voice(d(4, 'doubleDotted'), n(3, 4, 95, '<tremoloPicking duration="16"/><letRing/>'))]),
          beat(Fraction(31, 4), [voice(d(16), n(1, 5, 95, '<tapping/><staccato/>'))])]
    m3 = [beat(8, [voice(d(1), n(1, 5, 95, '', True))])]
    m4 = [beat(12, [voice(d(4), n(2, 7, 95, '<tremoloBar><point position="0" value="0"/><point position="6" value="-2"/>'
                                       '<point position="12" value="0"/></tremoloBar><fadeIn/>'))]),
          beat(13, [voice(d(4), n(2, 7, 95, '<bend><point position="0" value="0"/><point position="6" value="4"/>'
                                       '<point position="12" value="4"/></bend><heavyAccentuatedNote/>'))]),
          beat(14, [voice(d(4), n(3, 9, 60, '<ghostNote/><slide/>') + n(4, 9, 60, '<accentuatedNote/><vibrato/>'))])]
    drums = ''.join('<TGMeasure>' + ''.join(beat(m * 4 + q, [voice(d(4), n(1, 36 if q % 2 == 0 else 38) + n(2, 42, 70))])
                                            for q in range(4 if m < 3 else 3)) + '</TGMeasure>' for m in range(4))
    mixer = '<volume>127</volume><balance>64</balance><chorus>0</chorus><reverb>0</reverb><phaser>0</phaser><tremolo>0</tremolo>'
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<TuxGuitarFile><TGVersion major="2" minor="1" revision="0"/><TGSong>'
            '<name>Rich legacy</name><artist>Artist</artist><album>Album</album><author>Author</author><date>2026</date>'
            '<copyright>(c) owner</copyright><writer>Writer</writer><transcriber>Transcriber</transcriber>'
            '<comments>line one\nline two</comments>'
            f'<TGChannel><id>1</id><bank>0</bank><program>29</program>{mixer}<name>Lead</name></TGChannel>'
            f'<TGChannel><id>2</id><bank>128</bank><program>0</program>{mixer}<name>Kit</name>'
            '<TGChannelParameter key="gm-channel-1" value="9"/><TGChannelParameter key="gm-channel-2" value="9"/></TGChannel>'
            '<TGMeasureHeader><timeSignature numerator="4" denominator="4"/><tempo>100</tempo>'
            '<marker R="200" G="10" B="10">Intro</marker></TGMeasureHeader>'
            '<TGMeasureHeader><repeatOpen/><tripletFeel>eighth</tripletFeel></TGMeasureHeader>'
            '<TGMeasureHeader><repeatClose>1</repeatClose><repeatAlternative><alternative>1</alternative>'
            '</repeatAlternative></TGMeasureHeader>'
            '<TGMeasureHeader><timeSignature numerator="3" denominator="4"/><tempo>120</tempo>'
            '<repeatAlternative><alternative>2</alternative></repeatAlternative></TGMeasureHeader>'
            '<TGTrack maxFret="24"><name>Lead</name><channelId>1</channelId><color R="10" G="20" B="30"/>'
            + ''.join(f'<TGString>{p}</TGString>' for p in (64, 59, 55, 50, 45, 40)) +
            '<TGLyric from="1">la la la</TGLyric>'
            f'<TGMeasure><clef>treble</clef><keySignature>1</keySignature>{"".join(m1)}</TGMeasure>'
            f'<TGMeasure>{"".join(m2)}</TGMeasure><TGMeasure>{"".join(m3)}</TGMeasure><TGMeasure>{"".join(m4)}</TGMeasure>'
            '</TGTrack><TGTrack><name>Drums</name><channelId>2</channelId><color R="1" G="1" B="1"/>'
            + '<TGString>0</TGString>' * 6 + f'<TGLyric from="1"/>{drums}</TGTrack></TGSong></TuxGuitarFile>')


CHANNELS = {'t1': {'program': 29, 'bank': 0}, 't2': {'program': 0, 'bank': 128}}


def rich_song():
    return tgimport.read_tg(archive(rich_xml()))[0]


def adapt(song, label):
    """The rich song without what `label` cannot hold: voice 2 and strokes before 1.1, let ring before 1.2."""
    song = copy.deepcopy(song)
    for spec in song['score']['patterns'].values():
        if label == '1.0':
            spec['beats'] = [b for b in spec['beats'] if b['voice'] == 0]
        for b in spec['beats']:
            if label == '1.0':
                b.pop('stroke', None)
            for n in b['notes']:
                if label in ('1.0', '1.1'):
                    n.pop('let_ring', None)
    return song


class _W(bytearray):
    def n(self, value, size):
        self += int(value).to_bytes(size, 'big', signed=True)
        return self

    def text(self, value):
        self.append(len(value))
        self += value.encode('utf-16-be')
        return self


def old_tab(ver):
    """A two-track 0.7/0.8/0.9 file written from the pinned compat readers' layouts (TuxGuitar has no writers).

    Guitar: a two-note chord, a rest, eighth triplets, a tie across the bar line, velocity changes and the
    effects each version stores; drums on GM channel 10. 0.8/0.9 add a marker, swing, repeats and a tempo
    change; 0.9 adds lyrics and its three-byte effects.
    """
    q, tri, half = (4, 0, 0, (1, 1)), (8, 0, 0, (3, 2)), (2, 0, 0, (1, 1))
    old = {'vibrato': True} if ver < 9 else {'vibrato': True, 'fadeIn': True}
    bend = {'bend': [(0, 0), (6, 8), (12, 8)]}         # 0.7/0.8 halve positive bend values on reading
    if ver == 9:
        bend = {'bend': [(0, 0), (6, 4), (12, 4)], 'ghostNote': True}
    guitar = [[(q, [(1, 0, 95, False, old), (2, 1, 95, False, {'tremoloPicking': 16} if ver == 9 else {})]),
               (q, []),
               (tri, [(3, 2, 80, False, {'hammer': True})]),
               (tri, [(3, 4, 80, False, {})]),
               (tri, [(3, 5, 80, False, {'slide': True} if ver < 9 else {
                   'tremoloBar': [(0, 0), (6, -2), (12, 0)], 'palmMute': True})]),
               (q, [(1, 5, 110, False, bend)])],
              [(half, [(1, 5, 110, True, {})]),
               (half, [(2, 3, 70, False, {'deadNote': True} if ver < 9 else {
                   'harmonic': (2, 26), 'grace': (0, 2, 2, 95, 3), 'trill': (5, 16)})])]]
    drums = [[(q, [(1, 36, 95, False, {}), (2, 42, 70, False, {})]), (q, [(1, 38, 95, False, {})]),
              (q, [(1, 36, 95, False, {})]), (q, [(1, 38, 95, False, {})])] for _ in range(2)]
    tracks = [('Lead', 0, 25, [64, 59, 55, 50, 45, 40], guitar), ('Drums', 9, 0, [0] * 6, drums)]
    w = _W().text({7: 'TG_DEVEL-0.01', 8: 'TG_DEVEL-0.8', 9: tglegacy.PREFIX + '0.9'}[ver])
    for credit in ('Old tab', 'Artist', 'Album', 'Author'):
        w.text(credit)

    def duration(d):
        value, dotted, double, tuplet = d
        if ver == 7:
            w.n(value, 4).n(dotted, 1).n(double, 1).n(tuplet[0], 4).n(tuplet[1], 4)
            return
        w.n(dotted | double << 1 | (4 if tuplet != (1, 1) else 0), 1).n(value, 1)
        if tuplet != (1, 1):
            w.n(tuplet[0], 1).n(tuplet[1], 1)

    def effects(e):
        if ver == 7:
            w.n('vibrato' in e, 1).n('bend' in e, 1)
            if 'bend' in e:
                w.n(len(e['bend']), 4)
                for p, v in e['bend']:
                    w.n(p, 4).n(v, 4)
            w.n('deadNote' in e, 1).n('slide' in e, 1).n('hammer' in e, 1)
            return
        if ver == 8:
            bits = {'vibrato': 1, 'bend': 2, 'deadNote': 4, 'slide': 8, 'hammer': 16}
            w.n(sum(bits[k] for k in e), 1)
            if 'bend' in e:
                w.n(len(e['bend']), 1)
                for p, v in e['bend']:
                    w.n(p, 1).n(v, 1)
            return
        bits = {'bend': 1, 'tremoloBar': 2, 'harmonic': 4, 'grace': 8, 'trill': 16, 'tremoloPicking': 32,
                'vibrato': 0x40, 'deadNote': 0x80, 'slide': 0x100, 'hammer': 0x200, 'ghostNote': 0x400,
                'palmMute': 0x2000, 'fadeIn': 0x40000}
        w.n(sum(bits[k] for k in e), 3)
        for key, offset in (('bend', 0), ('tremoloBar', 12)):
            if key in e:
                w.n(len(e[key]), 1)
                for p, v in e[key]:
                    w.n(p, 1).n(v + offset, 1)
        if 'harmonic' in e:
            w.n(e['harmonic'][0], 1).n(e['harmonic'][1], 1)
        if 'grace' in e:
            for value in e['grace']:
                w.n(value, 1)
        if 'trill' in e:
            w.n(e['trill'][0], 1).n(e['trill'][1], 1)
        if 'tremoloPicking' in e:
            w.n(e['tremoloPicking'], 1)

    ticks = {q: 960, tri: 320, half: 1920}
    if ver > 7:
        w.n(2, 2)
        w.n(0x01 | 0x02 | 0x04 | 0x10, 1).n(4, 1)
        duration(q)
        w.n(100, 2).text('Intro').n(200, 2).n(10, 2).n(10, 2)
        w.n(0x02 | 0x08 | 0x20, 1).n(120, 2).n(1, 2).n(2, 1)
        w.n(len(tracks), 1)
    else:
        w.n(len(tracks), 4)
    for number, (name, route, program, tuning, measures) in enumerate(tracks, 1):
        if ver == 7:
            w.n(number, 8).text(name)
            for value in (route, route, program, 127, 64, 0, 0, 0, 0):
                w.n(value, 2)
            w.n(0, 1).n(0, 1).n(len(measures), 4)
        else:
            if ver == 9:
                w.n(1 if name == 'Lead' else 0, 1)
            w.text(name).n(0, 1)
            for value in (route, route, program, 127, 64, 0, 0, 0, 0):
                w.n(value, 1)
        for mi, beats in enumerate(measures):
            if ver == 7:
                w.n(mi + 1, 4).n(1000 + 4000 * mi, 8)
                at, notes, rests = 3840 * mi + 960, [], []
                for d, ns in beats:
                    (notes if ns else rests).extend([(at, d, n) for n in ns] or [(at, d, None)])
                    at += ticks[d]
                w.n(len(notes), 4)
                for at, d, (string, fret, velocity, tied, e) in notes:
                    w.n(fret, 4).n(at * 1000 // 960, 8)
                    duration(d)
                    w.n(velocity, 4).n(string, 4).n(tied, 1)
                    effects(e)
                w.n(len(rests), 4)
                for at, d, _ in rests:
                    w.n(at * 1000 // 960, 8)
                    duration(d)
                w.n(4, 4)
                duration(q)
                w.n(100, 4).n(1, 4).n(0, 4).n(0, 1).n(0, 4)
                continue
            w.n(0x03 if mi == 0 else 0, 1)
            components, previous, velocity = [], q, 95
            for bi, (d, ns) in enumerate(beats):
                for ni, note in enumerate(ns or [None]):
                    components.append((bi > 0 and ni == 0, d != previous and ni == 0, note))
                previous = d
            w.n(len(components), 2)
            for (next_beat, next_duration, note), d in zip(components, [d for d, ns in beats for _ in ns or [None]]):
                flags = (0x10 if next_beat else 0) | (0x20 if next_duration else 0)
                if note is None:
                    flags |= 0x02
                else:
                    string, fret, v, tied, e = note
                    flags |= 0x01 | (0x04 if tied else 0) | (0x08 if e else 0)
                    if ver == 9 and v != velocity:
                        flags |= 0x40
                w.n(flags, 1)
                if next_duration:
                    duration(d)
                if note is not None:
                    if ver == 8:
                        w.n(fret, 1).n(v, 1).n(string, 1)
                    else:
                        w.n(fret, 1).n(string, 1)
                        if flags & 0x40:
                            w.n(v, 1)
                            velocity = v
                    if e:
                        effects(e)
            if mi == 0:
                w.n(1, 1).n(0, 1)
        if ver == 7:
            w.n(len(tuning), 4)
            for i, pitch in enumerate(tuning, 1):
                w.n(i, 4).n(pitch, 4)
            for value in (10, 20, 30):
                w.n(value, 4)
        else:
            w.n(len(tuning), 1)
            for pitch in tuning:
                w.n(pitch, 1)
            w.n(24, 1)
            for value in (10, 20, 30):
                w.n(value, 2)
            if ver == 9 and name == 'Lead':
                w.n(1, 2).text('old words')
    return bytes(w)


def enharmonic_xml(key):
    """A chromatic octave twice under TG key signature `key`: plain, then with alternativeEnharmonic."""
    beats = []
    for mi in range(2):
        notes = []
        for i in range(12):
            flag = '<alternativeEnharmonic/>' if mi else ''
            notes.append(f'<TGBeat><preciseStart>{Q + (mi * 12 + i) * Q // 2}</preciseStart><voice><duration value="8"/>'
                         f'<note string="1" value="{i}" velocity="95">{flag}</note></voice>'
                         '<voice empty="true"><duration value="4"/></voice></TGBeat>')
        beats.append(''.join(notes))
    mixer = '<volume>127</volume><balance>64</balance><chorus>0</chorus><reverb>0</reverb><phaser>0</phaser><tremolo>0</tremolo>'
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<TuxGuitarFile><TGSong><name>Spelling</name><artist/><album/>'
            '<author/><date/><copyright/><writer/><transcriber/><comments/>'
            f'<TGChannel><id>1</id><bank>0</bank><program>0</program>{mixer}<name>Piano</name></TGChannel>'
            '<TGMeasureHeader><timeSignature numerator="12" denominator="8"/><tempo>120</tempo></TGMeasureHeader>'
            '<TGMeasureHeader/><TGTrack><name>Piano</name><channelId>1</channelId><color R="0" G="0" B="0"/>'
            '<TGString>60</TGString><TGLyric from="1"/>'
            f'<TGMeasure><clef>treble</clef><keySignature>{key}</keySignature>{beats[0]}</TGMeasure>'
            f'<TGMeasure>{beats[1]}</TGMeasure></TGTrack></TGSong></TuxGuitarFile>')


def header(label):
    text = tglegacy.PREFIX + label
    return bytes([len(text)]) + text.encode('utf-16-be')


class TestTgHeaderTrackFields(unittest.TestCase):
    """TG 2.0 measure-header lineBreak, track soloMute and per-measure clef/key changes, as native fields."""

    @staticmethod
    def xml():
        import xml.etree.ElementTree as ET
        root = ET.fromstring(rich_xml())
        song = root.find('TGSong')
        ET.SubElement(song.findall('TGMeasureHeader')[0], 'lineBreak')
        track = song.findall('TGTrack')[0]
        solo = ET.Element('soloMute'); solo.text = 'mute'
        track.insert(list(track).index(track.find('name')) + 1, solo)
        second = track.findall('TGMeasure')[1]
        for tag, value in (('clef', 'bass'), ('keySignature', '2')):
            node = second.find(tag)
            if node is None:
                node = ET.Element(tag); second.insert(0, node)
            node.text = value
        return ET.tostring(root, encoding='unicode')

    def test_read_write_read_keeps_the_fields(self):
        song, _ = tgimport.read_tg(archive(self.xml()))
        score = song['score']
        self.assertTrue(score['measures'][0]['line_break'])
        self.assertNotIn('line_break', score['measures'][1])
        self.assertEqual(score['tracks']['t1']['solo_mute'], 'mute')
        self.assertEqual(score['measures'][1]['staff']['t1'], dict(clef='bass', key=dict(fifths=2, mode='major')))
        channels = {t: dict(program=v['midi']['program'], bank=v['midi'].get('bank', 0)) for t, v in score['tracks'].items()}
        data, _ = tgimport.native_to_tg(song, tgimport._raw(song), channels=channels)
        again, _ = tgimport.read_tg(data)
        self.assertEqual(again['score'], score)

    def test_tempo_beat_unit_reads_plays_and_writes_as_tuxguitar(self):
        # TGTempo.setValueBase: 61 dotted quarters = 61*4//4 = 61, then 3*61//2 = 91 quarters; 80 eighths = 40 quarters.
        source = rich_xml().replace('<tempo>100</tempo>', '<tempo dotted="true">61</tempo>', 1)
        song, _ = tgimport.read_tg(archive(source))
        self.assertEqual(song['module']['tempo'], 91)
        self.assertEqual(song['score']['measures'][0]['tempo_unit'], dict(base=4, dotted=True, value=61))
        channels = {t: dict(program=v['midi']['program'], bank=v['midi'].get('bank', 0)) for t, v in song['score']['tracks'].items()}
        data, _ = tgimport.native_to_tg(song, tgimport._raw(song), channels=channels)
        again, _ = tgimport.read_tg(data)
        self.assertEqual(again['score'], song['score'])
        self.assertEqual(again['module']['tempo'], 91)
        song['score']['measures'][0]['tempo_unit'] = dict(base=8, dotted=False, value=80)   # plays 40, not 91
        with self.assertRaisesRegex(ValueError, 'set its beat unit again'):
            tgimport.native_to_tg(song, tgimport._raw(song), channels=channels)

    def test_validation(self):
        from vulturetracker import tablature
        song, _ = tgimport.read_tg(archive(self.xml()))
        for mutate, error in ((lambda s: s['score']['tracks']['t1'].update(solo_mute='loud'), 'solo_mute'),
                              (lambda s: s['score']['measures'][0].update(line_break=1), 'line_break'),
                              (lambda s: s['score']['measures'][1].update(staff={'nope': {'clef': 'bass'}}), 'existing track'),
                              (lambda s: s['score']['measures'][1].update(staff={'t1': {'clef': 'soprano'}}), 'unsupported clef')):
            with self.subTest(error=error):
                bad = copy.deepcopy(song)
                mutate(bad)
                with self.assertRaisesRegex(ValueError, error):
                    tablature.validate_score(bad)


class TestTgLegacyRead(unittest.TestCase):
    def test_tg_written_legacy_matches_source_with_tg_writer_losses_only(self):
        source = semantics(tgimport.read_tg(archive(rich_xml()))[0])
        for ver in (11, 12, 13, 15):
            with self.subTest(ver=ver):
                song, warnings = tgimport.read_tg(fixture(f'rich.v{ver}'))
                expected = copy.deepcopy(source)
                # What TuxGuitar's own legacy writers drop: maxFret and pick strokes, and let ring before 1.2.
                expected[1]['t1']['max_fret'] = 29
                for beat in expected[3]:
                    beat.pop('pick_stroke', None)
                if ver == 11:
                    for position in expected[4]:
                        position.pop('let_ring', None)
                self.assertEqual(semantics(song), expected)
                self.assertEqual(len(expected[4]), 48)
                self.assertEqual(song['module']['message'].count('GM output routing'), int(ver < 13))
                self.assertEqual(any('per-track channel data' in w for w in warnings), ver < 13)

    def test_v10_single_voice_matches_tuxguitar_rewrite(self):
        ours = semantics(tgimport.read_tg(fixture('rich.v10'))[0])
        self.assertEqual(ours, semantics(tgimport.read_tg(fixture('rich.v10.current'))[0]))
        self.assertEqual({b['voice'] for b in ours[3]}, {0})
        self.assertFalse(any('stroke' in b or 'stem' in b for b in ours[3]))

    def test_13_8_starts_follow_precise_voice_ends_not_ticks(self):
        for name in ('seed13.v15', 'seed13.v10'):
            song, _ = tgimport.read_tg(fixture(name))
            beats = song['score']['patterns']['m1']['beats']
            self.assertEqual([Fraction(*b['at']) for b in beats], [Fraction(4 * i, 13) for i in range(13)])
            self.assertEqual(sum(len(b['notes']) for b in beats), 12)

    def test_detection_is_by_content_and_errors_are_specific(self):
        good = fixture('rich.v15')
        cases = {'1.4': header('1.4') + good[len(header('1.5')):],
                 'truncated': good[:-3], 'trailing': good + b'\0'}
        messages = {'1.4': 'unsupported TuxGuitar File Format 1.4', 'truncated': 'truncated', 'trailing': 'trailing bytes'}
        for case, data in cases.items():
            with self.subTest(case=case), self.assertRaisesRegex(ValueError, messages[case]):
                tgimport.read_tg(data)
        with self.assertRaisesRegex(ValueError, 'archive/XML'):
            tgimport.read_tg(b'not a tab at all')
        self.assertIsNone(tglegacy.version(archive(rich_xml())))
        self.assertEqual(tglegacy.version(good), '1.5')

    def test_negative_ending_mask_refuses(self):
        # Header 3 of rich.v15: flags close|alternative|feel, close 1, ending mask 1, feel none.
        data = bytearray(fixture('rich.v15'))
        song = tgimport.read_tg(bytes(data))[0]
        self.assertEqual(song['score']['measures'][2]['endings'], [1])
        tail = bytes([0x58, 0, 1, 1, 1])
        self.assertEqual(bytes(data).count(tail), 1)
        at = bytes(data).index(tail)
        data[at + 3] = 0x81
        with self.assertRaisesRegex(ValueError, 'ending 8'):
            tgimport.read_tg(bytes(data))

    def test_melodic_gm_routes_are_a_notice_route_9_refuses(self):
        import xml.etree.ElementTree as ET
        root = ET.fromstring(rich_xml())
        channel = root.find('.//TGChannel')
        for value in ('3', '9'):
            for p in channel.findall('TGChannelParameter'):
                channel.remove(p)
            ET.SubElement(channel, 'TGChannelParameter', key='gm-channel-1', value=value)
            ET.SubElement(channel, 'TGChannelParameter', key='gm-channel-2', value='4')
            data = archive(ET.tostring(root, encoding='unicode'))
            with self.subTest(value=value):
                if value == '9':
                    with self.assertRaisesRegex(ValueError, 'other than 9'):
                        tgimport.read_tg(data)
                else:
                    _, warnings = tgimport.read_tg(data)
                    self.assertIn('channel 1: TuxGuitar GM output routing 3/4 is not stored natively', ' '.join(warnings))

    def test_import_tg_publishes_a_legacy_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            src = folder / 'old.tg'
            src.write_bytes(fixture('rich.v13'))
            song, warnings = tgimport.import_tg(src, folder / 'song.yaml', folder / 'samples')
            self.assertTrue((folder / 'song.yaml').exists())
            self.assertEqual(len(song['score']['tracks']), 2)


class TestTgOldRead(unittest.TestCase):
    def test_old_formats_read_as_tuxguitar_reads_them(self):
        # old.v0N.tg-read: TuxGuitar 2.1.0's v07/v08/v09 reader on old_tab(N), rewritten by TG as 2.0.
        for ver in (7, 8, 9):
            with self.subTest(ver=ver):
                data = old_tab(ver)
                self.assertEqual(tglegacy.version(data), f'0.{ver}')
                song, warnings = tgimport.read_tg(data)
                self.assertEqual(semantics(song), semantics(tgimport.read_tg(fixture(f'old.v0{ver}.tg-read'))[0]))
                notes = [n for p in song['score']['patterns'].values() for b in p['beats'] if b['track'] == 't1'
                         for n in b['notes']]
                self.assertEqual(len(notes), 8)
                self.assertEqual(notes[5]['bend']['points'][1], {'position': 6, 'value': 4})   # 0.7/0.8 halve
                self.assertEqual(len(song['score']['ties']), 1)
                self.assertEqual(song['score']['tracks']['t2']['midi']['bank'], 128)
                self.assertEqual('swing' in song['score']['measures'][1], ver > 7)
                self.assertEqual('lyrics' in song['score']['tracks']['t1'], ver == 9)
                self.assertTrue(any('per-track channel data' in w for w in warnings))
        self.assertEqual(notes[7]['harmonic'], {'type': 'artificial', 'data': 2})   # 0.9: offset byte - 24

    def test_old_refusals_are_specific(self):
        data = bytearray(old_tab(7))
        start = (1000).to_bytes(8, 'big')
        data[data.index(start):data.index(start) + 8] = (1500).to_bytes(8, 'big')
        with self.assertRaisesRegex(ValueError, 'measure 1: measure start 1440 does not follow'):
            tgimport.read_tg(bytes(data))
        with self.assertRaisesRegex(ValueError, 'truncated'):
            tgimport.read_tg(old_tab(9)[:-5])


class TestTgLegacyWrite(unittest.TestCase):
    @staticmethod
    def export(song, label):
        return tgimport.native_to_tg(song, tgimport._raw(song), channels=CHANNELS, version=label)

    def test_each_writable_version_reads_back_with_listed_display_losses_only(self):
        source = rich_song()
        for label in tglegacy.WRITABLE:
            with self.subTest(label=label):
                song = adapt(source, label)
                data, report = self.export(song, label)
                self.assertEqual(tglegacy.version(data), label)
                self.assertEqual(report['format'], 'TuxGuitar File Format ' + label)
                expected = semantics(song)
                expected[1]['t1']['max_fret'] = 29
                for beat in expected[3]:
                    beat.pop('pick_stroke', None)
                self.assertEqual(semantics(tgimport.read_tg(data)[0]), expected)
                self.assertIn('track 1: max fret 24 (legacy formats read 29)', report['losses'])
                self.assertIn('track 1, measure 2, beat 1: pick stroke up (legacy formats have none)', report['losses'])
                self.assertEqual('song comments (stored from 1.2)' in report['losses'], label in ('1.0', '1.1'))
                self.assertTrue(any(w.startswith('Not stored in TuxGuitar File Format') for w in report['warnings']))

    def test_tuxguitar_reads_our_exports_as_we_do(self):
        # rich-ours.vNN.tg-read: TuxGuitar 2.1.0's compat reader on our export, rewritten by TG as 2.0.
        for label in ('1.0', '1.5'):
            with self.subTest(label=label):
                data, _ = self.export(adapt(rich_song(), label), label)
                theirs = fixture(f'rich-ours.v{label.replace(".", "")}.tg-read')
                self.assertEqual(semantics(tgimport.read_tg(data)[0]), semantics(tgimport.read_tg(theirs)[0]))

    def test_sounding_losses_refuse(self):
        source = rich_song()
        cases = [('1.0', source, 'one voice; voice 2'),
                 ('1.1', source, 'let ring is not stored before'),
                 ('1.4', source, "unsupported TuxGuitar file format '1.4'")]
        stroke_only = adapt(source, '1.0')
        stroke_only['score']['patterns']['m1']['beats'][0]['stroke'] = {'direction': 'down', 'value': 8}
        cases.append(('1.0', stroke_only, 'stores no strokes'))
        for label, song, reason in cases:
            with self.subTest(label=label, reason=reason), self.assertRaisesRegex(ValueError, reason):
                self.export(copy.deepcopy(song), label)


# TuxGuitar 2.1.0's TGMusicKeyUtils.noteName for enharmonic_xml(key), read by the installed TG
# (scratch/tg-format/enharmonic.py): twelve plain notes, then the same twelve with alternativeEnharmonic.
TG_NAMES = {
    0: 'C C# D D# E F F# G G# A A# B B# Db D Eb Fb E# Gb G Ab A Bb Cb',
    3: 'C C# D D# E F F# G G# A A# B B# Db D Eb Fb E# Gb G Ab A Bb Cb',
    6: 'C C# D D# E E# F# G G# A A# B B# Db D Eb Fb F Gb G Ab A Bb Cb',
    7: 'B# C# D D# E E# F# G G# A A# B C Db D Eb Fb F Gb G Ab A Bb Cb',
    10: 'C Db D Eb E F Gb G Ab A Bb B B# C# D D# Fb E# F# G G# A A# Cb',
    13: 'C Db D Eb E F Gb G Ab A Bb Cb B# C# D D# Fb E# F# G G# A A# B',
    14: 'C Db D Eb Fb F Gb G Ab A Bb Cb B# C# D D# E E# F# G G# A A# B',
}


class TestTgEnharmonic(unittest.TestCase):
    @staticmethod
    def names(song, key):
        out = []
        for name in ('m1', 'm2'):
            for b in song['score']['patterns'][name]['beats']:
                for n in b['notes']:
                    s = n.get('spelling') or tgimport._tg_spelling(n['pitch'], key, False)
                    out.append(s['step'] + {1: '#', -1: 'b', 0: ''}[s['alter']])
        return ' '.join(out)

    def test_alternative_enharmonic_is_native_spelling_both_ways(self):
        for key, expected in TG_NAMES.items():
            with self.subTest(key=key):
                song, _ = tgimport.read_tg(archive(enharmonic_xml(key)))
                self.assertEqual(self.names(song, key), expected)
                self.assertFalse(any('spelling' in n for b in song['score']['patterns']['m1']['beats'] for n in b['notes']))
                data, _ = tgimport.native_to_tg(song, tgimport._raw(song), channels={'t1': {'program': 0, 'bank': 0}})
                flags = tgimport._xml(data).findall('.//alternativeEnharmonic')
                self.assertEqual(len(flags), sum('spelling' in n for b in song['score']['patterns']['m2']['beats']
                                                 for n in b['notes']))
                self.assertEqual(self.names(tgimport.read_tg(data)[0], key), expected)

    def test_unreachable_spelling_refuses_and_legacy_lists_the_loss(self):
        song, _ = tgimport.read_tg(archive(enharmonic_xml(0)))
        data, report = tgimport.native_to_tg(song, tgimport._raw(song), channels={'t1': {'program': 0, 'bank': 0}},
                                             version='1.5')
        self.assertIn('track 1: alternative enharmonic spellings (legacy formats spell by key)', report['losses'])
        self.assertIsNone(tgimport._xml(tgimport.native_to_tg(
            *(lambda s: (s, tgimport._raw(s)))(tgimport.read_tg(data)[0]), channels={'t1': {'program': 0, 'bank': 0}})[0]
        ).find('.//alternativeEnharmonic'))
        song['score']['patterns']['m1']['beats'][2]['notes'][0]['spelling'] = {'step': 'E', 'alter': -2}   # D as Ebb
        with self.assertRaisesRegex(ValueError, 'neither the key spelling TuxGuitar writes nor its alternative'):
            tgimport.native_to_tg(song, tgimport._raw(song), channels={'t1': {'program': 0, 'bank': 0}})


def without_beat(song, pattern, track, at):
    song = copy.deepcopy(song)
    beats = song['score']['patterns'][pattern]['beats']
    beats.remove(next(b for b in beats if b['track'] == track and b['voice'] == 0 and b['at'] == at))
    return song


class TestTgOpenPlacement(unittest.TestCase):
    """TuxGuitar's open path (TGReadSongAction -> updatePreciseStart) places each beat at the end of its voices."""

    def test_reader_places_beats_as_tuxguitar_opens_them(self):
        import xml.etree.ElementTree as ET
        root = ET.fromstring(rich_xml())
        m1 = root.findall('.//TGTrack')[1].find('TGMeasure')
        m1.remove(m1.findall('TGBeat')[1])            # a hole at quarter 1 of the drums
        song, warnings = tgimport.read_tg(archive(ET.tostring(root, encoding='unicode')))
        self.assertEqual([w.split(';')[0] for w in warnings if 'moved' in w],
                         ['track 2, measure 1, beat 2: moved from quarter 2 to 1',
                          'track 2, measure 1, beat 3: moved from quarter 3 to 2'])
        # drumgap.tg-read: TuxGuitar 2.1.0 opening the same file (normalizing probe), rewritten as 2.0.
        self.assertEqual(semantics(song), semantics(tgimport.read_tg(fixture('drumgap.tg-read'))[0]))

    def test_reader_refuses_deleted_or_overflowing_beats(self):
        import xml.etree.ElementTree as ET
        root = ET.fromstring(rich_xml())
        first = root.findall('.//TGTrack')[1].find('TGMeasure').find('TGBeat')
        for voice in first.findall('voice'):
            first.remove(voice)
            ET.SubElement(ET.SubElement(first, 'voice', empty='true'), 'duration', value='4')
        with self.assertRaisesRegex(ValueError, "track 2, measure 1, beat 2: TuxGuitar deletes this beat"):
            tgimport.read_tg(archive(ET.tostring(root, encoding='unicode')))
        root = ET.fromstring(rich_xml())
        # Guitar measure 3: a whole note; a voice-2 note stored at quarter 2 opens after it, past the bar.
        m3 = root.findall('.//TGTrack')[0].findall('TGMeasure')[2]
        late = ET.SubElement(m3, 'TGBeat')
        ET.SubElement(late, 'preciseStart').text = str(Q + 10 * Q)
        ET.SubElement(ET.SubElement(late, 'voice', empty='true'), 'duration', value='4')
        v = ET.SubElement(late, 'voice')
        ET.SubElement(v, 'duration', value='4')
        ET.SubElement(v, 'note', string='6', value='0', velocity='95')
        with self.assertRaisesRegex(ValueError, 'track 1, measure 3, beat 2: TuxGuitar opens this beat at quarter 4'):
            tgimport.read_tg(archive(ET.tostring(root, encoding='unicode')))

    def test_writer_preserves_sparse_scores_with_reported_export_only_rests(self):
        source = rich_song()
        held = without_beat(source, 'm1', 't1', [1, 1])
        data, _ = TestTgLegacyWrite.export(held, '1.5')   # voice 2 sounds across the hole: placement holds
        self.assertEqual(semantics(tgimport.read_tg(data)[0])[4], semantics(held)[4])
        cases = [(without_beat(source, 'm1', 't2', [1, 1]), 'track 2, measure 1, beat 2: TuxGuitar would move this '
                  'beat from quarter 2 to 1'),
                 (without_beat(source, 'm1', 't2', [0, 1]), 'track 2, measure 1, beat 2: TuxGuitar would delete'),
                 (without_beat(source, 'm2', 't2', [0, 1]), 'track 2, measure 2, beat 1: TuxGuitar would move this '
                  'beat from quarter 1 to 0')]
        for song, reason in cases:
            for label in ('2.0', '1.5', '1.0'):
                with self.subTest(reason=reason, label=label):
                    original = adapt(song, label)
                    before = copy.deepcopy(original)
                    data, report = TestTgLegacyWrite.export(original, label)
                    restored, _ = tgimport.read_tg(data)
                    self.assertGreater(report['generated_rests'], 0)
                    self.assertEqual(semantics(restored)[4], semantics(original)[4])
                    self.assertEqual(original, before)

    def test_string_count_limit_before_1_5(self):
        source = rich_song()
        song = tgimport._xml(tgimport.native_to_tg(source, tgimport._raw(source), channels=CHANNELS)[0])
        drums = song.findall('TGTrack')[1]
        for string in drums.findall('TGString')[3:]:
            drums.remove(string)
        tglegacy.from_xml(song, '1.5')
        for label in ('1.2', '1.3'):
            with self.subTest(label=label), self.assertRaisesRegex(ValueError, 'stores 4..7 strings'):
                tglegacy.from_xml(song, label)


class TestTgCoincidentCohorts(unittest.TestCase):
    """Separate TGBeat objects remain separate after opening, export and another edit."""

    @staticmethod
    def source():
        import xml.etree.ElementTree as ET
        root = ET.fromstring(rich_xml()).find('TGSong')
        for tag in ('TGChannel', 'TGMeasureHeader', 'TGTrack'):
            for node in root.findall(tag)[1:]:
                root.remove(node)
        track = root.find('TGTrack')
        for measure in track.findall('TGMeasure')[1:]:
            track.remove(measure)
        track.find('TGLyric').text = ''
        measure = track.find('TGMeasure')
        for beat in measure.findall('TGBeat'):
            measure.remove(beat)
        for at, voices, text, stroke in (
                (0, (0, 1), '', None),
                (1, (0,), 'first object', 'down'),
                (1, (1,), 'second object', 'up'),
                (2, (0,), '', None)):
            beat = ET.SubElement(measure, 'TGBeat')
            ET.SubElement(beat, 'preciseStart').text = str(Q * (at + 1))
            if text:
                ET.SubElement(beat, 'text').text = text
            if stroke:
                ET.SubElement(beat, 'stroke', direction=stroke, value='8')
            for vi in (0, 1):
                voice = ET.SubElement(beat, 'voice', **({} if vi in voices else {'empty': 'true'}))
                ET.SubElement(voice, 'duration', value='4')
                if vi in voices:
                    ET.SubElement(voice, 'note', string=str(vi + 1), value=str(at), velocity='95')
        return root

    @staticmethod
    def read(source):
        import xml.etree.ElementTree as ET
        root = ET.Element('TuxGuitarFile')
        root.append(source)
        return tgimport.read_tg(archive(ET.tostring(root, encoding='unicode')))

    @staticmethod
    def snapshot(song):
        return [(b['voice'], Fraction(*b['at']), b.get('cohort', 0), b.get('text'), b.get('stroke'),
                 [(n['string'], n['fret']) for n in b['notes']])
                for b in song['score']['patterns']['m1']['beats']]

    def test_current_and_legacy_roundtrip_preserve_objects_and_metadata(self):
        song, _ = self.read(self.source())
        before = copy.deepcopy(song)
        colliding = [b for b in song['score']['patterns']['m1']['beats'] if b['at'] == [1, 1]]
        self.assertEqual([(b['voice'], b.get('cohort', 0)) for b in colliding], [(0, 0), (1, 1)])
        for version in ('2.0', '1.1', '1.2', '1.3', '1.5'):
            with self.subTest(version=version):
                data, report = tgimport.native_to_tg(song, tgimport._raw(song), channels={'t1': CHANNELS['t1']},
                                                    version=version)
                reopened, _ = tgimport.read_tg(data)
                self.assertEqual(self.snapshot(reopened), self.snapshot(song))
                self.assertEqual(report['generated_rests'], 0)
        self.assertEqual(song, before)

    def test_opening_collision_retains_stable_preplacement_order(self):
        source = self.source()
        measure = source.find('TGTrack/TGMeasure')
        beats = measure.findall('TGBeat')
        beats[2].find('preciseStart').text = str(Q * 5 // 2)  # stored at 1.5, opens at 1
        measure.remove(beats[2]); measure.append(beats[2])   # document order differs from TG sorting
        song, warnings = self.read(source)
        self.assertTrue(any('moved from quarter 3/2 to 1' in warning for warning in warnings))
        self.assertEqual(self.snapshot(song), self.snapshot(self.read(self.source())[0]))

    def test_export_filler_and_sparse_ranks_do_not_merge_authored_cohorts(self):
        song, _ = self.read(self.source())
        beats = song['score']['patterns']['m1']['beats']
        beats.remove(beats[1])  # voice 1 begins at quarter 1: export must add one rest
        beats[0]['cohort'] = 7  # a valid unnormalized singleton, not an empty origin slot
        original = copy.deepcopy(song)
        for version in ('2.0', '1.5'):
            data, report = tgimport.native_to_tg(song, tgimport._raw(song), channels={'t1': CHANNELS['t1']}, version=version)
            reopened, _ = tgimport.read_tg(data)
            self.assertEqual(report['generated_rests'], 1)
            colliding = [b for b in reopened['score']['patterns']['m1']['beats'] if b['at'] == [1, 1]]
            self.assertEqual([(b['voice'], b.get('cohort', 0), b.get('text')) for b in colliding],
                             [(0, 0, 'first object'), (1, 1, 'second object')])
        self.assertEqual(song, original)

    def test_roundtrip_then_free_edit_keeps_independent_voice_starts(self):
        from vulturetracker import tablature as tab
        song, _ = self.read(self.source())
        results = []
        for version in ('2.0', '1.5'):
            data, _ = tgimport.native_to_tg(song, tgimport._raw(song), channels={'t1': CHANNELS['t1']}, version=version)
            reopened, _ = tgimport.read_tg(data)
            changed, _ = tab.score_command(reopened, tgimport._raw(reopened),
                dict(action='set_duration', occurrence='o1', track='t1', voice=0,
                     beats=['t1_b1_v1'], written=dict(value=8), free=True))
            starts = [(b['voice'], Fraction(*b['at'])) for b in changed['score']['patterns']['m1']['beats']]
            self.assertEqual(starts, [(0, Fraction(0)), (1, Fraction(0)), (0, Fraction(1, 2)),
                                      (1, Fraction(1)), (0, Fraction(3, 2))])
            results.append(self.snapshot(changed))
        self.assertEqual(*results)

    def test_duplicate_same_voice_remains_invalid(self):
        source = self.source()
        measure = source.find('TGTrack/TGMeasure')
        measure.append(copy.deepcopy(measure.findall('TGBeat')[1]))
        before = copy.deepcopy(source)
        with self.assertRaisesRegex(ValueError, 'overlapping beats in the same voice'):
            tgimport.read_tree(source)
        import xml.etree.ElementTree as ET
        self.assertEqual(ET.tostring(source), ET.tostring(before))


if __name__ == '__main__':
    unittest.main()
