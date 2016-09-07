from collections import defaultdict

from urh import constants
from urh.signalprocessing.Interval import Interval
from urh.signalprocessing.MessageType import MessageType
from urh.signalprocessing.Participant import Participant
from urh.signalprocessing.ProtocoLabel import ProtocolLabel


class LabelAssigner(object):
    def __init__(self, messages):
        """

        :type messages: list of Message
        """
        self.__messages = messages
        self.sync_end = None
        self.preamble_end = None
        self.common_intervals = defaultdict(set)
        self.common_intervals_per_message = defaultdict(list)

    @property
    def is_initialized(self):
        return len(self.common_intervals) > 0 if len(self.__messages) > 0 else True

    def __search_constant_intervals(self):
        if self.preamble_end is None:
            self.find_preamble()

        self.common_intervals.clear()
        self.common_intervals_per_message.clear()

        for i in range(0, len(self.__messages)):
            for j in range(i + 1, len(self.__messages)):
                range_start = 0
                constant_length = 0
                bits_i = self.__messages[i].decoded_bits_str[self.preamble_end:]
                bits_j = self.__messages[j].decoded_bits_str[self.preamble_end:]
                end = min(len(bits_i), len(bits_j)) - 1

                for k, (bit_i, bit_j) in enumerate(zip(bits_i, bits_j)):
                    if bit_i == bit_j:
                        constant_length += 1
                    else:
                        if constant_length > constants.SHORTEST_CONSTANT_IN_BITS:
                            interval = Interval(self.preamble_end+range_start, self.preamble_end+k-1)
                            self.common_intervals[(i, j)].add(interval)
                            self.common_intervals_per_message[i].append(interval)
                            self.common_intervals_per_message[j].append(interval)

                        constant_length = 0
                        range_start = k + 1

                if constant_length > constants.SHORTEST_CONSTANT_IN_BITS:
                    interval = Interval(self.preamble_end+range_start, self.preamble_end+ end)
                    self.common_intervals[(i, j)].add(interval)
                    self.common_intervals_per_message[i].append(interval)
                    self.common_intervals_per_message[j].append(interval)

    def common_intervals_for_participant(self, participant: Participant):
        return {(i, j): intervals for (i, j), intervals in self.common_intervals.items()
                if self.__messages[i].participant == participant and self.__messages[j].participant == participant}


    def print_common_intervals(self):
        print("Raw common intervals\n=================")
        for msg_index in sorted(self.common_intervals):
            print(msg_index, sorted(r for r in self.common_intervals[msg_index] if r.start != self.preamble_end), end=" ")
            print(" ".join([self.__get_hex_value_for_msg(self.__messages[msg_index[0]], interval) for interval in sorted(r for r in self.common_intervals[msg_index] if r.start != self.preamble_end)]))

        print("Common intervals per participant\n=================")
        for participant in sorted({msg.participant for msg in self.__messages}):
            name = participant.name if participant is not None else "None"
            print(name + "\n-----------------")
            common_intervals_for_participant =  self.common_intervals_for_participant(participant)
            for msg_index in sorted(common_intervals_for_participant):
                print(msg_index,
                      sorted(r for r in common_intervals_for_participant[msg_index] if r.start != self.preamble_end), end=" ")
                print(" ".join([self.__get_hex_value_for_msg(self.__messages[msg_index[0]], interval) for interval in
                                sorted(r for r in common_intervals_for_participant[msg_index] if r.start != self.preamble_end)]))

        print("Merged common intervals\n=================")
        for msg_index in sorted(self.common_intervals_per_message):
            interval_info = ""
            for interval in sorted(set(self.common_intervals_per_message[msg_index])):
                interval_info += str(interval) + " (" + str(self.common_intervals_per_message[msg_index].count(interval)) + ") "

            print(msg_index, interval_info)



    def __get_hex_value_for_msg(self, msg, interval):
        start, end = msg.convert_range(interval.start + 1, interval.end, from_view=0, to_view=1, decoded=True)
        return msg.decoded_hex_str[start:end]

    def find_preamble(self) -> ProtocolLabel:
        preamble_ends = [pre_end for pre_end in (msg.find_preamble_end() for msg in self.__messages) if pre_end]

        if len(preamble_ends) == 0:
            self.preamble_end = 0
            return None

        self.preamble_end = max(preamble_ends, key=preamble_ends.count)
        return ProtocolLabel(name="Preamble", start=0, end=self.preamble_end-1, color_index=None)


    def find_sync(self) -> ProtocolLabel:
        """
        Find synchronization sequence (sync) in protocol.
        The sync starts right after preamble and is constant regarding range for all messages. Different sync values are possible.
        The sync is chosen by comparing all constant ranges that lay right behind the preamble and chose the most frequent one.

        :return:
        """
        if not self.is_initialized:
            self.__search_constant_intervals()

        possible_sync_pos = defaultdict(int)
        for const_range in (cr for const_interval in self.common_intervals.values() for cr in const_interval):
            const_range = Interval(4 * ((const_range.start + 1) // 4) - 1, 4 * ((const_range.end + 1) // 4) - 1) # align to nibbles
            possible_sync_pos[const_range] += int(const_range.start == self.preamble_end)

        sync_interval = max(possible_sync_pos, key=possible_sync_pos.__getitem__)

        self.sync_end = sync_interval.end
        return ProtocolLabel(start=sync_interval.start + 1, end=sync_interval.end - 1, name="Sync", color_index=None)

    def find_constants(self):
        """
        Return a list of labels over constants in the protocol.
        A constant is the largest common interval, that appears in all constant intervals of all messages.
        It suffices to search for the first message, because if the constant does not appear here, it cant be a constant.

        :rtype: list of ProtocolLabel
        """
        if not self.is_initialized:
            self.__search_constant_intervals()

        common_constant_intervals = set()

        if (0,1) not in self.common_intervals:
            return []

        for candidate in self.common_intervals[(0, 1)]:
            for j in range(1, len(self.__messages)):
                overlapping_intervals = {candidate.find_common_interval(interval) for interval in self.common_intervals[(0, j)]}
                overlapping_intervals.discard(None)

                if len(overlapping_intervals) == 0:
                    candidate = None
                    break
                else:
                    candidate = max(overlapping_intervals)

            if candidate is None:
                continue

            overlapping_candidate = next((c for c in common_constant_intervals if c.overlaps_with(candidate)), None)

            if overlapping_candidate is None:
                common_constant_intervals.add(candidate)
            else:
                common_constant_intervals.remove(overlapping_candidate)
                common_constant_intervals.add(candidate.find_common_interval(overlapping_candidate))

        return [ProtocolLabel(start=interval.start, end=interval.end, name="Constant #{0}".format(i+1),
                              color_index=None) for i, interval in enumerate(common_constant_intervals)]

    def find_byte_length(self):
        """
        Find the byte length using a scoring algorithm.

        :return:
        """
        if self.sync_end is None:
            self.find_sync()

        scores = defaultdict(int)
        weights = {-5: 1, -4: 2, -3: 3, -2: 4, -1: 5, 0: 6}

        for message in self.__messages:
            byte_start = int(message.convert_index(self.sync_end + 1, 0, 2, decoded=True)[0])
            byte_len = message.get_byte_length(decoded=True) - byte_start
            for i, byte in enumerate(message.get_bytes(start=byte_start, decoded=True)):
                diff = byte - byte_len
                bit_range = message.convert_index(byte_start + i, 2, 0, decoded=True)
                if diff in weights:
                    scores[bit_range] += weights[diff]
        try:
            length_range = max(scores, key=scores.__getitem__)
        except ValueError:
            return None

        return ProtocolLabel(start=int(length_range[0]), end=int(length_range[1]) - 1, name="Length", color_index=None)

    def auto_assign_to_message_type(self, message_type: MessageType):
        preamble = self.find_preamble()
        if preamble is not None:
            message_type.add_label(preamble, allow_overlapping=False)

        sync = self.find_sync()
        if sync is not None:
            message_type.add_label(sync, allow_overlapping=False)

        for constant_lbl in self.find_constants():
            message_type.add_label(constant_lbl, allow_overlapping=False)

        length_label = self.find_byte_length()
        if length_label is not None:
            message_type.add_label(length_label, allow_overlapping=False)
