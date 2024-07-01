import os
import math
import serial
import serial.tools.list_ports
import threading
import tkinter as tk
import tkinter.ttk as ttk
from datetime import datetime
from tkinter import filedialog
from tkinter import Button, Entry, Label, StringVar



class SerialPortManager:
    def __init__(self, main_window, row):
        self._selected_port = None
        self._port_opened = False
        self._serial_port = None
        self.port_label = Label(main_window, text="Port:", fg="white")
        self.port_label.grid(row=row, column=0)

        self.v_combo = StringVar()
        self.combo = ttk.Combobox(main_window, values=self.get_serial_ports())
        self.combo.bind('<<ComboboxSelected>>', self.on_select)
        self.combo.bind('<Button-1>', self.on_click)
        self.combo.grid(row=row, column=1, sticky='w')

    def selected_port(self):
        return self._selected_port

    def selected_port(self, value):
        self._selected_port = value
        self.port_opened = False

    def port_status(self):
        return self._port_opened

    def port_open(self, status_text):

        if not self._port_opened:
            try:
                self._serial_port = serial.Serial(self.selected_port)
                self._port_opened = self._serial_port.is_open
            except serial.SerialException:
                self._port_opened = False
                status_text.set("Serial port open faild")
                
        return self._port_opened

    def port_close(self):
        if self._port_opened:
            self._serial_port.close()
            self._port_opened = False

    def on_click(self, event=None):
        event.widget['values'] = self.get_serial_ports()

    def on_select(self, event=None):
        self.selected_port = event.widget.get()

    def get_serial_ports(self):
        ports = serial.tools.list_ports.comports()
        for port, desc, hwid in sorted(ports):
            print(desc)
        return [port for port, desc, hwid in sorted(ports) if desc.startswith("Pico") or desc.startswith("USB Serial Device")]

    def start_trassmission(self):
        self._serial_port.write(b'1')
        self.crc_mode = self.check_crc_mode()

    def check_crc_mode(self):
        return self._wait_for_chars([b'C', b'\x15'])

    def build_xmodem_packet(self, idx, payload):
        packet = bytearray()
        packet.extend(self._int_to_bytes(0x01, 1))  # SOH
        packet.extend(self._int_to_bytes(idx, 2))  # packet index
        packet.extend(self._int_to_bytes(len(payload), 2))  # packet length

        
        packet.extend(payload)
        packet.extend(self._int_to_bytes(sum(payload) & 0xff, 1))  # checksum
        
        return packet

    def serial_send_xmodem_first_packet(self, address, total_packet):
        payload = self._int_to_bytes(address, 4) + self._int_to_bytes(total_packet, 4)
        
        self._send_packet_and_wait_for_ack(0x00, payload)

    def wait_for_ack(self):
        return self._wait_for_chars([b'\x06', b'\x15']) == b'\x06'

    def serial_send_xmodem_file(self, bitstream_data, total_packet, status_text):
        for idx in range(total_packet):
            data = bitstream_data[idx*256:(idx+1)*256]
            while not self._send_packet_and_wait_for_ack(idx+1, data):
                pass
            status_text.set(f"Sending bitstream slice {idx+1}/{total_packet}")

    def stop_trassmission(self):
        self._serial_port.write(b'\x04')  # EOT
        self._serial_port.read_until(b'\x06')

    def _int_to_bytes(self, value, length):
        return [(value >> i*8) & 0xff for i in reversed(range(length))]

    def _wait_for_chars(self, chars):
        while True:
            ch = self._serial_port.read()
            if ch in chars:
                return ch

    def _send_packet_and_wait_for_ack(self, idx, payload):
        packet_to_send = self.build_xmodem_packet(idx, payload)
        self._serial_port.write(packet_to_send)
        return self.wait_for_ack()

class BitstreamManager:
    def __init__(self, main_window, name, row):
        self.name = name
        self.config_len = 0
        self.file_name = StringVar(main_window, value="")
        self.v_address = StringVar(main_window, value='0x00000000')
        self.v_check = tk.IntVar()
        self._create_gui(main_window, row)

    def _create_gui(self, main_window, row):
        self.checkbox = tk.Checkbutton(main_window, text="", variable=self.v_check)
        self.checkbox.grid(row=row, column=0)
        self.entry_file_name = Entry(main_window, textvariable=self.file_name, width = 50)
        self.entry_file_name.grid(row=row, column=1)
        self.btn_choose_file = Button(main_window, name="config_btn_{}".format(self.name), text="...", command=self._select_bitstream_file)
        self.btn_choose_file.grid(row=row, column=2)
        self.lable=Label(main_window, text=" @", fg="white")
        self.lable.grid(row=row, column=3)
        self.entry_address = Entry(main_window, textvariable=self.v_address, width = 9) 
        self.entry_address.grid(row=row, column=4)

    def _select_bitstream_file(self):
        file_name = filedialog.askopenfilename(filetypes=[("Bitstream files", "*.bin")])
        if file_name != "":
            try:
                with open(file_name, "rb") as bitfile:
                    bitstream_data = bitfile.read()
                self.config_len = len(bitstream_data)
                self.file_name.set(file_name)
            except IOError:
                tk.messagebox.showerror("Error", "File cannot be opened")
                
                
class FileUploadManager:
    def __init__(self, serial_config, config_list, status_text):
        self.serial_config = serial_config
        self.config_list = config_list
        self.status_text = status_text

    def _is_valid_config(self, config):
        if config.v_check.get() != 1:
            return False

        file_name = config.file_name.get()
        if file_name == "":
            print("Please choose a file for configuration {}".format(config.name))
            return False

        _, extension = os.path.splitext(file_name)
        if extension.lower() != '.bin': #Todo: add *.bit file support
            print("Invalid file type, only *.bin files are supported.")
            return False

        address = config.v_address.get()
        if address == "":
            print("Please enter an address for configuration {}".format(config.name))
            return False

        address_int = int(address, 16)  # Assumes the address is in hexadecimal
        if address_int % 4096 != 0:
            print("The address for configuration {} is not a multiple of 4096".format(config.name))
            return False

        return True

    def _is_address_occupied(self, address, valid_configs):
        for valid_config in valid_configs:
            if valid_config.v_address.get() == address:
                print("The address for configuration {} is already used by configuration{}".format(config.name, valid_config.name))
                return True
        return False

    def check_configurations(self):
        valid_configs = []
        for config in self.config_list:
            if self._is_valid_config(config) and not self._is_address_occupied(config.v_address.get(), valid_configs):
                valid_configs.append(config)
                print("Config 1: write {} to address {} with {} Bytes.".format(config.file_name.get(), config.v_address.get(), config.config_len))
        return valid_configs

    def _read_bitstream_file(self, file_name):  # Helper method to read bitstream file
        with open(file_name, "rb") as bitfile:
            return bitfile.read()
        
    def _upload_bitstream(self, config):
        file_name = config.file_name.get()
        bitstream_data = self._read_bitstream_file(file_name)

        address = int(config.v_address.get(), 16)
        file_len = len(bitstream_data)
        total_packet = math.floor(file_len/256) if file_len % 256 == 0 else math.floor(file_len/256)+1

        self.serial_config.start_trassmission()
        self.status_text.set("Hand shaking")
        self.serial_config.serial_send_xmodem_first_packet(address, total_packet)
        self.status_text.set("Erasing flash for configuration {}".format(config.name))

        self.serial_config.serial_send_xmodem_file(bitstream_data, total_packet, self.status_text)
        self.serial_config.stop_trassmission()

        print("Upload bitstreams finished.")
        self.status_text.set("Upload bitstreams finished.")

    def upload_bitstreams(self):
        valid_configs = self.check_configurations()
        if not valid_configs:
            print("No valid configurations to be uploaded.")
            return

        print("{} bitstreams to be uploaded".format(len(valid_configs)))
        if not self.serial_config.port_open(self.status_text):
            tk.messagebox.showerror("Error", "Serial port open failed")
            print("Abort serial port open failed")
            self.status_text.set("Abort, due to serial port open failed")
            return

        for config in valid_configs:
            self._upload_bitstream(config)

        self.serial_config.port_close()

    def flash_in_thread(self):
        threading.Thread(target=self.upload_bitstreams).start()
          
# --- main ---
if __name__ == '__main__':
    
    BITSTREAM_CONFIG_ROWS = [0, 1, 2, 4, 5, 6]
    SERIAL_CONFIG_ROW = 7
    STATUS_PREFIX_ROW = 8
    BUTTON_ROW = 7
    
    selected_port = None
    port_opened = False
    serial_port = None
    main_window = tk.Tk()

    main_window.title("Elastic Node Flashing Tool")

    config_list = [BitstreamManager(main_window, str(i+1), BITSTREAM_CONFIG_ROWS[i]) for i in range(6)]

    serial_config = SerialPortManager(main_window, row=SERIAL_CONFIG_ROW)

    status_prefix = Label(main_window, text="Status:")
    status_prefix.grid(row=STATUS_PREFIX_ROW, column=0, columnspan=1)
    
    status_text = StringVar()
    status_text.set("Ready")
    status_label = Label(main_window, textvariable=status_text)
    status_label.grid(row=STATUS_PREFIX_ROW, column=1, columnspan=5, sticky='w')

    file_uploader = FileUploadManager(serial_config, config_list, status_text)
    btn_start = Button(main_window, text="Flash Bitstreams", command = file_uploader.flash_in_thread)
    btn_start.grid(row=BUTTON_ROW, column=3, sticky='e', columnspan=3)

    main_window.mainloop()