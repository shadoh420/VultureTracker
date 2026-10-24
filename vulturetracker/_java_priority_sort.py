# Copyright (c) 2009, 2013, Oracle and/or its affiliates. All rights reserved.
# Copyright 2009 Google Inc.  All Rights Reserved.
# DO NOT ALTER OR REMOVE COPYRIGHT NOTICES OR THIS FILE HEADER.
#
# This code is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License version 2 only, as
# published by the Free Software Foundation.  Oracle designates this
# particular file as subject to the "Classpath" exception as provided
# by Oracle in the LICENSE file that accompanied this code.
#
# This code is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License
# version 2 for more details (a copy is included in the LICENSE file that
# accompanied this code).
#
# You should have received a copy of the GNU General Public License version
# 2 along with this work; if not, write to the Free Software Foundation,
# Inc., 51 Franklin St, Fifth Floor, Boston, MA 02110-1301 USA.
#
# Please contact Oracle, 500 Oracle Parkway, Redwood Shores, CA 94065 USA
# or visit www.oracle.com if you need additional information or have any
# questions.

# "CLASSPATH" EXCEPTION TO THE GPL
#
# Certain source files distributed by Oracle America and/or its affiliates are
# subject to the following clarification and special exception to the GPL, but
# only where Oracle has expressly included in the particular source file's header
# the words "Oracle designates this particular file as subject to the "Classpath"
# exception as provided by Oracle in the LICENSE file that accompanied this code."
#
#     Linking this library statically or dynamically with other modules is making
#     a combined work based on this library.  Thus, the terms and conditions of
#     the GNU General Public License cover the whole combination.
#
#     As a special exception, the copyright holders of this library give you
#     permission to link this library with independent modules to produce an
#     executable, regardless of the license terms of these independent modules,
#     and to copy and distribute the resulting executable under terms of your
#     choice, provided that you also meet, for each linked independent module,
#     the terms and conditions of the license of that module.  An independent
#     module is a module which is not derived from or based on this library.  If
#     you modify this library, you may extend this exception to your version of
#     the library, but you are not obligated to do so.  If you do not wish to do
#     so, delete this exception statement from your version.

"""Generic sorting adaptation; no chord-specific data, scoring or policy.

Adapted to Python and isolated on 2026-10-20 from OpenJDK24 java.util.TimSort
by Josh Bloch, originally adapted from Tim Peters's Python list sort.
The Classpath exception above is retained for this modified version.
SPDX-License-Identifier: GPL-2.0-only WITH Classpath-exception-2.0
Source: https://github.com/openjdk/jdk/blob/jdk-24%2B36/src/java.base/share/classes/java/util/TimSort.java
Full license: https://github.com/openjdk/jdk/blob/jdk-24%2B36/LICENSE
"""


class _PrioritySort:
    """Java TimSort merge decisions for a supplied comparator."""
    def __init__(self, rows, compare):
        self.rows = rows
        self.compare = compare
        self.runs = []
        self.min_gallop = 7

    def gallop(self, key, rows, base, length, hint, right):
        # right=False finds before equals, right=True after equals.
        def past(index):
            value = self.compare(key, rows[base + index])
            return value >= 0 if right else value > 0
        last, offset = 0, 1
        if past(hint):
            limit = length - hint
            while offset < limit and past(hint + offset):
                last, offset = offset, offset * 2 + 1
            last, offset = last + hint, min(offset, limit) + hint
        else:
            limit = hint + 1
            while offset < limit and not past(hint - offset):
                last, offset = offset, offset * 2 + 1
            last, offset = hint - min(offset, limit), hint - last
        last += 1
        while last < offset:
            middle = (last + offset) // 2
            if past(middle):
                last = middle + 1
            else:
                offset = middle
        return offset

    def merge(self, index):
        rows = self.rows
        start, left = self.runs[index]
        middle, right = self.runs[index + 1]
        self.runs[index:index + 2] = [(start, left + right)]
        skip = self.gallop(rows[middle], rows, start, left, 0, True)
        start, left = start + skip, left - skip
        if not left:
            return
        right = self.gallop(rows[start + left - 1], rows, middle, right, right - 1, False)
        if right:
            if left <= right:
                self.merge_low(start, left, middle, right)
            else:
                self.merge_high(start, left, middle, right)

    def merge_low(self, start, left, middle, right):
        rows = self.rows
        temp = rows[start:start + left]
        a, b, dest = 0, middle + 1, start + 1
        rows[start] = rows[middle]
        right -= 1
        gallop = self.min_gallop
        if right and left > 1:
            while left > 1 and right:
                wins_a = wins_b = 0
                while left > 1 and right:
                    if self.compare(rows[b], temp[a]) < 0:
                        rows[dest] = rows[b]
                        dest, b, right = dest + 1, b + 1, right - 1
                        wins_b, wins_a = wins_b + 1, 0
                    else:
                        rows[dest] = temp[a]
                        dest, a, left = dest + 1, a + 1, left - 1
                        wins_a, wins_b = wins_a + 1, 0
                    if (wins_a | wins_b) >= gallop:
                        break
                if left <= 1 or not right:
                    break
                while left > 1 and right:
                    wins_a = self.gallop(rows[b], temp, a, left, 0, True)
                    rows[dest:dest + wins_a] = temp[a:a + wins_a]
                    dest, a, left = dest + wins_a, a + wins_a, left - wins_a
                    if left <= 1:
                        break
                    rows[dest] = rows[b]
                    dest, b, right = dest + 1, b + 1, right - 1
                    if not right:
                        break
                    wins_b = self.gallop(temp[a], rows, b, right, 0, False)
                    rows[dest:dest + wins_b] = rows[b:b + wins_b]
                    dest, b, right = dest + wins_b, b + wins_b, right - wins_b
                    if not right:
                        break
                    rows[dest] = temp[a]
                    dest, a, left = dest + 1, a + 1, left - 1
                    if left == 1:
                        break
                    gallop -= 1
                    if wins_a < 7 and wins_b < 7:
                        break
                if left <= 1 or not right:
                    break
                gallop = max(0, gallop) + 2
            self.min_gallop = max(1, gallop)
        if left == 1:
            rows[dest:dest + right] = rows[b:b + right]
            rows[dest + right] = temp[a]
        elif left == 0:
            raise ValueError('Comparison method violates its general contract!')
        else:
            rows[dest:dest + left] = temp[a:a + left]

    def merge_high(self, start, left, middle, right):
        rows = self.rows
        temp = rows[middle:middle + right]
        a, b, dest = start + left - 2, right - 1, middle + right - 2
        rows[dest + 1] = rows[a + 1]
        left -= 1
        gallop = self.min_gallop
        if left and right > 1:
            while left and right > 1:
                wins_a = wins_b = 0
                while left and right > 1:
                    if self.compare(temp[b], rows[a]) < 0:
                        rows[dest] = rows[a]
                        dest, a, left = dest - 1, a - 1, left - 1
                        wins_a, wins_b = wins_a + 1, 0
                    else:
                        rows[dest] = temp[b]
                        dest, b, right = dest - 1, b - 1, right - 1
                        wins_b, wins_a = wins_b + 1, 0
                    if (wins_a | wins_b) >= gallop:
                        break
                if not left or right <= 1:
                    break
                while left and right > 1:
                    wins_a = left - self.gallop(temp[b], rows, start, left, left - 1, True)
                    rows[dest - wins_a + 1:dest + 1] = rows[a - wins_a + 1:a + 1]
                    dest, a, left = dest - wins_a, a - wins_a, left - wins_a
                    if not left:
                        break
                    rows[dest] = temp[b]
                    dest, b, right = dest - 1, b - 1, right - 1
                    if right == 1:
                        break
                    wins_b = right - self.gallop(rows[a], temp, 0, right, right - 1, False)
                    rows[dest - wins_b + 1:dest + 1] = temp[b - wins_b + 1:b + 1]
                    dest, b, right = dest - wins_b, b - wins_b, right - wins_b
                    if right <= 1:
                        break
                    rows[dest] = rows[a]
                    dest, a, left = dest - 1, a - 1, left - 1
                    if not left:
                        break
                    gallop -= 1
                    if wins_a < 7 and wins_b < 7:
                        break
                if not left or right <= 1:
                    break
                gallop = max(0, gallop) + 2
            self.min_gallop = max(1, gallop)
        if right == 1:
            rows[dest - left + 1:dest + 1] = rows[a - left + 1:a + 1]
            rows[dest - left] = temp[b]
        elif right == 0:
            raise ValueError('Comparison method violates its general contract!')
        else:
            rows[dest - right + 1:dest + 1] = temp[:right]

    def sort(self):
        rows, size = self.rows, len(self.rows)
        if size < 2:
            return
        minimum, remainder = size, 0
        while minimum >= 32:
            remainder |= minimum & 1
            minimum >>= 1
        minimum += remainder
        start = 0
        while start < size:
            end = start + 1
            if end < size:
                descending = self.compare(rows[end], rows[start]) < 0
                end += 1
                while end < size and ((self.compare(rows[end], rows[end - 1]) < 0) == descending):
                    end += 1
                if descending:
                    rows[start:end] = reversed(rows[start:end])
            stop = min(size, max(end, start + minimum))
            for at in range(end, stop):
                pivot, low, high = rows[at], start, at
                while low < high:
                    middle = (low + high) // 2
                    if self.compare(pivot, rows[middle]) < 0:
                        high = middle
                    else:
                        low = middle + 1
                rows[low + 1:at + 1] = rows[low:at]
                rows[low] = pivot
            self.runs.append((start, stop - start))
            start = stop
            while len(self.runs) > 1:
                index = len(self.runs) - 2
                lengths = [length for _, length in self.runs]
                if ((index > 0 and lengths[index - 1] <= lengths[index] + lengths[index + 1]) or
                        (index > 1 and lengths[index - 2] <= lengths[index] + lengths[index - 1])):
                    if lengths[index - 1] < lengths[index + 1]:
                        index -= 1
                elif lengths[index] > lengths[index + 1]:
                    break
                self.merge(index)
        while len(self.runs) > 1:
            index = len(self.runs) - 2
            if index > 0 and self.runs[index - 1][1] < self.runs[index + 1][1]:
                index -= 1
            self.merge(index)
