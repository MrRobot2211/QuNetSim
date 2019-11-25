import time
import numpy as np
import sys

sys.path.append("../..")
from components.host import Host
from components.network import Network
from components.daemon_thread import DaemonThread
from components import protocols
from components.logger import Logger
from cqc.pythonLib import CQCConnection, qubit
import sys

thread_1_return = None
thread_2_return = None

SYN = '10'
SYN_ACK = '11'
ACK = '01'
WAIT_TIME = 5
MAX_NUM_OF_TRANSMISSIONS = 10


def handshake_sender(host, receiver_id):
    """
    Establishes a classical TCP-like handshake with the receiver .
    If successful starts the transmission of qubits , otherwise terminated the connection.

    :param host: Sender of qubits
    :param receiver_id: ID of the receiver
    :return: If successful returns True, otherwise False
    """

    # Create an EPR pair.
    qa_1 = qubit(host.cqc)
    qa_2 = qubit(host.cqc)

    qa_1.H()
    qa_1.cnot(qa_2)

    # Send a half of EPR pair and the SYN message to Bob.
    _, ack_received = host.send_qubit(receiver_id, qa_2, await_ack=True)
    if ack_received is False:
        Logger.get_instance().log('ACK is not received')
        return False
    ack_received = host.send_classical(receiver_id, SYN, await_ack=True)
    if ack_received is False:
        Logger.get_instance().log('ACK is not received')
        return False

    syn_seq_num = host.get_sequence_number(receiver_id)

    # Receive the qubits Bob has sent (qubit 2 and qubit 3) for SYN-ACK.
    qb_2 = host.get_data_qubit(receiver_id, wait=WAIT_TIME)
    if qb_2 is None:
        return False
    qb_2 = qb_2['q']

    qb_3 = host.get_data_qubit(receiver_id, wait=WAIT_TIME)
    if qb_3 is None:
        return False
    qb_3 = qb_3['q']

    # Receive the classical message Bob has sent for SYN-ACK.
    message_recv = host.get_message_w_seq_num(receiver_id, syn_seq_num + 2, wait=WAIT_TIME)
    if message_recv is None:
        return False
    message_recv = message_recv[0]['message']
    if message_recv == '11':
        Logger.get_instance().log("SYN-ACK is received by Alice")
    else:
        Logger.get_instance().log('Connection terminated - 1 ')
        return False

    # Make a Bell State measurement on qubit 1 and qubit 2.
    qa_1.cnot(qb_2)
    qa_1.H()
    qa_1_check = qa_1.measure()
    qb_2_check = qb_2.measure()

    # If measurement results are as expected, send Bob a ACK message and the qubit 3 that he has sent previously.
    # Else report that there is something wrong.
    if qa_1_check == 0 and qb_2_check == 0:
        latest_seq_num = host.get_sequence_number(receiver_id)
        ack_received = host.send_classical(receiver_id, ACK, True)
        if ack_received is False:
            Logger.get_instance().log('ACK is not received')
            return False
        _, ack_received = host.send_qubit(receiver_id, qb_3, True)
        if ack_received is False:
            Logger.get_instance().log('ACK is not received')
            return False
        start_time = time.time()
        while time.time() - start_time < WAIT_TIME:
            if host.get_sequence_number(receiver_id) == latest_seq_num + 2 and host.classical[0]['message'] == 'ACK':
                return True
        return False
    else:
        Logger.get_instance().log("Something is wrong.")
        return False


def handshake_receiver(host, sender_id):
    """
    Establishes a classical TCP-like handshake with the sender .
    If successful starts to receive the qubits , otherwise terminated the connection.

    :param host: Receiver host
    :param sender_id: ID of the sender
    :return: If successful returns True, otherwise False
    """
    latest_seq_num = host.get_sequence_number(sender_id)

    # Receive the EPR half of Alice and the SYN message
    qb_2 = host.get_data_qubit(sender_id, wait=WAIT_TIME)
    if qb_2 is None:
        Logger.get_instance().log('qb_2 is None')
        return False
    qb_2 = qb_2['q']

    message_recv = host.get_message_w_seq_num(sender_id, (latest_seq_num + 1), wait=WAIT_TIME)
    if not message_recv:
        Logger.get_instance().log('No message has arrived')
        return False

    message_recv = message_recv[0]['message']

    if message_recv == '10':
        Logger.get_instance().log("SYN is received by Bob")
    else:
        return False

    # Create an EPR pair.
    qb_3 = qubit(host.cqc)
    qb_4 = qubit(host.cqc)
    qb_3.H()
    qb_3.cnot(qb_4)

    # Send half of the EPR pair created (qubit 3) and send back the qubit 2 that Alice has sent first.
    _, ack_received = host.send_qubit(sender_id, qb_2, await_ack=True)

    if ack_received is False:
        Logger.get_instance().log('ACK is not received')
        return False

    _, ack_received = host.send_qubit(sender_id, qb_3, await_ack=True)
    if ack_received is False:
        Logger.get_instance().log('ACK is not received')
        return False

    # Send SYN-ACK message.
    host.send_classical(sender_id, SYN_ACK, True)
    latest_seq_num = host.get_sequence_number(sender_id)

    # Receive the ACK message.
    start_time = time.time()
    ack_message_received = False
    while time.time() - start_time < WAIT_TIME and not ack_message_received:
        latest_messages = host.get_message_w_seq_num(sender_id, latest_seq_num)
        for messages in latest_messages:
            if messages['message'] == '01':
                Logger.get_instance().log('ACK is received by Bob')
                ack_message_received = True

        if ack_message_received:
            break

    # Receive the qubit 3.
    qa_3 = host.get_data_qubit(sender_id, wait=WAIT_TIME)
    if qa_3 is None:
        return False
    qa_3 = qa_3['q']

    # Make a Bell State measurement in qubit 3 and qubit 4.
    qa_3.cnot(qb_4)
    qa_3.H()

    qa_3_check = qa_3.measure()
    qb_4_check = qb_4.measure()

    # If measurement results are as expected , establish the TCP connection.
    # Else report that there is something wrong.
    if qa_3_check == 0 and qb_4_check == 0:
        Logger.get_instance().log("TCP connection established.")
        return True
    else:
        Logger.get_instance().log("Something is wrong.")
        return False


def qubit_send_w_retransmission(host, q_size, receiver_id, checksum_size_per_qubit):
    """
    Sends the data qubits along with checksum qubits , with the possibility of retransmission.

    :param host: Sender of qubits
    :param q_size: Number of qubits to be sent
    :param receiver_id: ID of the receiver
    :param checksum_size_per_qubit: Checksum qubit per data qubit size
    :return:
    """
    bit_arr = np.random.randint(2, size=q_size)
    Logger.get_instance().log('Bit array to be sent: ' + str(bit_arr))
    qubits = []
    for i in range(q_size):
        q_tmp = qubit(host.cqc)
        if bit_arr[i] == 1:
            q_tmp.X()
        qubits.append(q_tmp)

    check_qubits = host.add_checksum(host.cqc, qubits, checksum_size_per_qubit)
    checksum_size = int(q_size / checksum_size_per_qubit)
    qubits.append(check_qubits)
    checksum_cnt = 0
    for i in range(q_size + checksum_size):
        if i < q_size:
            q = qubits[i]
        else:
            q = qubits[q_size][checksum_cnt]
            checksum_cnt = checksum_cnt + 1

        q_successful = True
        ack_expected = True
        number_of_retransmissions = 0
        while ack_expected and number_of_retransmissions < MAX_NUM_OF_TRANSMISSIONS:
            Logger.get_instance().log('Alice prepares qubit')
            err_1 = qubit(host.cqc)
            # encode logical qubit
            q.cnot(err_1)

            host.send_qubit(receiver_id, q, await_ack=True)
            start_time = time.time()
            while time.time() - start_time < WAIT_TIME:
                if len(host.classical) != 0 and host.classical[0]['message'] == 'ACK':
                    Logger.get_instance().log('Alice: Bob received the qubit')
                    err_1.release()
                    ack_expected = False
                    q_successful = False
                    # return True
                    break
                    # Remove err_1 from simulqron

            if q_successful:
                Logger.get_instance().log('Alice: Bob did not receive the qubit')
                # re-introduce a qubit to the system and correct the error
                q = qubit(host.cqc)
                err_1.cnot(q)

            number_of_retransmissions += 1

        if number_of_retransmissions == 10:
            Logger.get_instance().log("Alice: too many attempts made")
            return False
    return True


def qubit_recv_w_retransmission(host, q_size, sender_id, checksum_size_per_qubit):
    """
    Receives the data qubits with the possibility of retransmission.
    Then decodes the qubits , with checksum qubits and outputs the classical bits that has been sent.

    :param host: Receiver host
    :param q_size: Qubit size to be received
    :param sender_id: ID of the sender
    :param checksum_size_per_qubit: Checksum qubit per data qubit size
    :return:
    """

    qubits = []
    number_of_retranmissions = 0
    checksum_size = int(q_size / checksum_size_per_qubit)
    for i in range(q_size + checksum_size):
        while len(qubits) < (q_size + checksum_size):
            need_retransmission = True
            while need_retransmission and number_of_retranmissions < MAX_NUM_OF_TRANSMISSIONS:
                q = host.get_data_qubit(sender_id, wait=WAIT_TIME)
                if q is not None:
                    need_retransmission = False
                    qubits.append(q)
                    Logger.get_instance().log('Bob: received qubit')
                else:
                    Logger.get_instance().log("Bob: didn't receive the qubit")
                    host.send_classical('Alice', 'NACK', False)
                    # Simulate qubit loss
                    q.release()
                    number_of_retranmissions += 1

            if number_of_retranmissions == MAX_NUM_OF_TRANSMISSIONS:
                Logger.get_instance().log("Bob: too many attempts made")
                return False

    checksum_qubits = []
    checksum_cnt = 0
    checksum_size = int(q_size / checksum_size_per_qubit)
    for i in range(len(qubits)):
        if checksum_cnt < checksum_size:
            checksum_qubits.append(qubits[q_size + i]['q'])
            checksum_cnt = checksum_cnt + 1

    checksum_cnt = 1
    for i in range(len(qubits) - checksum_size):
        qubits[i]['q'].cnot(checksum_qubits[checksum_cnt - 1])
        if i == (checksum_cnt * checksum_size_per_qubit - 1):
            checksum_cnt = checksum_cnt + 1

    errors = 0
    for i in range(len(checksum_qubits)):
        if checksum_qubits[i].measure() != 0:
            errors += 1

    print('---------')
    if errors == 0:
        Logger.get_instance().log('No error exist in UDP packet')
    else:
        Logger.get_instance().log('There were errors in the UDP transmission')
    print('---------')

    rec_bits = []
    for i in range(len(qubits) - checksum_size):
        rec_bits.append(qubits[i]['q'].measure())

    if errors == 0:
        print('---------')
        Logger.get_instance().log('Receiver received the classical bits: ' + str(rec_bits))
        print('---------')
        return True


def qtcp_sender(host, q_size, receiver_id, checksum_size_per_qubit):
    """
    Establishes a handshake and sends the data qubits to the receiver if handshake is successful.

    :param host: Sender of qubits
    :param q_size: Number of qubits to be sent
    :param receiver_id: ID of the receiver
    :param checksum_size_per_qubit: Checksum qubit per data qubit size
    :return:
    """
    global thread_1_return
    tcp_connection = handshake_sender(host, receiver_id)
    if not tcp_connection:
        Logger.get_instance().log('Connection terminated.')
        thread_1_return = False
        return
    else:
        packet_transmission = qubit_send_w_retransmission(host, q_size, receiver_id, checksum_size_per_qubit)
        if packet_transmission:
            Logger.get_instance().log('Connection was successful.')
            thread_1_return = True
            return
        else:
            Logger.get_instance().log('Connection was not successful.')
            thread_1_return = False
            return


def qtcp_receiver(host, q_size, sender_id, checksum_size_per_qubit):
    """
    Establishes a handshake and receives the data qubits from the sender if handshake is successful.

    :param host: Receiver host
    :param q_size: Qubit size to be received
    :param sender_id: ID of the sender
    :param checksum_size_per_qubit: Checksum qubit per data qubit size
    :return:

    """
    tcp_connection = handshake_receiver(host, sender_id)
    global thread_2_return
    if not tcp_connection:
        Logger.get_instance().log('Connection terminated.')
        thread_2_return = False
        return
    else:
        packet_transmission = qubit_recv_w_retransmission(host, q_size, sender_id, checksum_size_per_qubit)
        if packet_transmission:
            thread_2_return = True
            return
        else:
            thread_2_return = True
            return


def main():
    global thread_1_return
    global thread_2_return

    network = Network.get_instance()
    nodes = ["Alice", "Bob"]
    network.start(nodes)
    network.delay = 0.5

    print('')
    with CQCConnection("Alice") as Alice, CQCConnection("Bob") as Bob:
        host_alice = Host('alice', Alice)
        host_alice.add_connection('bob')
        host_alice.add_c_connection('eve')
        host_alice.max_ack_wait = 30
        host_alice.delay = 0.2
        host_alice.start()

        host_bob = Host('bob', Bob)
        host_bob.max_ack_wait = 30
        host_bob.delay = 0.2
        host_bob.add_connection('alice')
        host_bob.add_q_connection('dean')
        host_bob.start()

        network.add_host(host_alice)
        network.add_host(host_bob)
        network.x_error_rate = 0
        network.packet_drop_rate = 0

        q_size = 6
        checksum_per_qubit = 2

        DaemonThread(qtcp_sender, args=(host_alice, q_size, host_bob.host_id, checksum_per_qubit))
        DaemonThread(qtcp_receiver, args=(host_bob, q_size, host_alice.host_id, checksum_per_qubit))

        while thread_1_return is None or thread_2_return is None:
            if thread_1_return is False or thread_2_return is False:
                Logger.get_instance().log('TCP Connection not successful : EXITING')
                sys.exit(1)
            pass

        thread_1_return = None
        thread_2_return = None

        Logger.get_instance().log('PACKET 1')

        DaemonThread(qtcp_sender, args=(host_alice, q_size, host_bob.host_id, checksum_per_qubit))
        DaemonThread(qtcp_receiver, args=(host_bob, q_size, host_alice.host_id, checksum_per_qubit))

        while thread_1_return is None or thread_2_return is None:
            if thread_1_return is False or thread_2_return is False:
                Logger.get_instance().log('TCP Connection not successful : EXITING')
                sys.exit(1)
            pass

        Logger.get_instance().log('PACKET 2')

        DaemonThread(qtcp_sender, args=(host_alice, q_size, host_bob.host_id, checksum_per_qubit))
        DaemonThread(qtcp_receiver, args=(host_bob, q_size, host_alice.host_id, checksum_per_qubit))

        while thread_1_return is None or thread_2_return is None:
            if thread_1_return is False or thread_2_return is False:
                Logger.get_instance().log('TCP Connection not successful : EXITING')
                sys.exit(1)
            pass

        start_time = time.time()
        while time.time() - start_time < 150:
            pass

        network.stop(stop_hosts=True)
        exit()


if __name__ == '__main__':
    main()