"""
CircuitPython driver for the OPT4001 ALS
    SOT-5X3 variant

**Authors**
Thomas Damiani

**Sofware Requirements**

* Adafruit CircuitPython Firmware (8.0.5+)
    https://github.com/adafruit/circuitpython/releases/tag/8.0.5
* Adafruit Bus Device Library
    https://github.com/adafruit/Adafruit_CircuitPython_BusDevice
* Adafruit Register Library
    https://github.com/adafruit/Adafruit_CircuitPython_Register
"""

import time
from micropython import const

from adafruit_bus_device.i2c_device import I2CDevice
from adafruit_register.i2c_bits import RWBits
from adafruit_register.i2c_bit import ROBit, RWBit

try:
    from typing_extensions import Literal
except ImportError:
    pass

# Registers as descirbed in page 25 of datasheet
RESULT_H        = const(0x00)
RESULT_L        = const(0x01)
FIFO_0_H        = const(0x02)
FIFO_0_L        = const(0x03)
FIFO_1_H        = const(0x04)
FIFO_1_L        = const(0x05)
FIFO_2_H        = const(0x06)
FIFO_2_L        = const(0x07)
THRESHOLD_L     = const(0x08)
THRESHOLD_H     = const(0x09)
CONFIGURATION   = const(0x0A)
FLAGS           = const(0x0C)
DEVICE_ID       = const(0x11)


class OPT4001:
    """
    Configuration settings
    Locations of these bits are descirbed in page 30 and 31 of the datasheet
    """
    quick_wakeup            = RWBit(CONFIGURATION, 15, register_width=2, lsb_first=False)
    lux_range               = RWBits(4, CONFIGURATION, 10, register_width=2, lsb_first=False)
    conversion_time         = RWBits(4, CONFIGURATION, 6, register_width=2, lsb_first=False)
    operating_mode          = RWBits(2, CONFIGURATION, 4, register_width=2, lsb_first=False)
    latch                   = RWBit(CONFIGURATION, 3, register_width=2, lsb_first=False)
    int_pol                 = RWBit(CONFIGURATION, 2, register_width=2, lsb_first=False)
    fault_count             = RWBits(2, CONFIGURATION, 0, register_width=2, lsb_first=False)

    # flags
    overload_flag           = ROBit(FLAGS, 3, register_width=2, lsb_first=False)
    conversion_ready_flag   = ROBit(FLAGS, 2, register_width=2, lsb_first=False)
    flag_h                  = ROBit(FLAGS, 1, register_width=2, lsb_first=False)
    flag_L                  = ROBit(FLAGS, 0, register_width=2, lsb_first=False)

    # default address 0x44
    def __init__(self, i2c_bus,
                 address=0x44,
                 quick_wakeup=False,
                 lux_range=0b1100,
                 conversion_time=0b1000,
                 operating_mode=0b00,
                 latch=True,
                 int_pol=False,
                 fault_count=0b00) -> "OPT4001":
        # initliaze i2c device
        self.i2c_device = I2CDevice(i2c_bus, address)

        """------ configure the OPT4001 ------"""
        """
        Quick Wake-up from Standby in one-shot mode. gets out of standby faster as the cost of
        larger power consumption.
        """
        self.quick_wakeup = quick_wakeup
        """
        Lux range
        | 0         | 1         | 2         | 3         | 4         | 5         |
        | 459lux    | 918lux    | 1.8klux   | 3.7klux   | 7.3klux   | 14.7klux  |
        -------------------------------------------------------------------------
        | 6         | 7         | 8         | 12        |
        | 29.4klux  | 58.7klux  | 117.4klux | auto      |
        """
        self.lux_range = lux_range

        """
        Conversion Time
        | 0         | 1         | 2         | 3         | 4         | 5         |
        | 600us     | 1ms       | 1.8ms     | 3.4ms     | 6.5ms     | 12.7ms    |
        -------------------------------------------------------------------------
        | 6         | 7         | 8         | 9         | 10        | 11        |
        | 25ms      | 50ms      | 100ms     | 200ms     | 400ms     | 800ms     |
        """
        self.conversion_time = conversion_time

        """
        Operating Mode
        0: Power Down
        1: Forced Auto-range One-shot
        2: One-shot
        3: Continuous
        """
        self.operating_mode = operating_mode

        """
        Interrupt reporting mechanisms as described in page 14 and 15 of the datasheet

        0: Transparent hysteresis mode
        1: Latched window mode
        """
        self.latch = latch

        """
        INT pin polarity
        0: Active Low
        1: Active High
        """
        self.int_pol = int_pol

        """
        Fault count describes how many consecutive faults are required to trigger the theshold
        mechanisms.
        0: one fault
        1: two faults
        2: four faults
        3: eight faults
        """
        self.fault_count = fault_count

        self.buf = bytearray(3)

        # check that the ID of the device matches what the datasheet says the ID should be
        if not self.check_id():
            raise RuntimeError("Could not read device id")

    def read_u16(self, addr) -> None:
        # first write will be to the address register
        self.buf[0] = addr
        with self.i2c_device as i2c:
            # write to the address register, then read from register into buffer[0] and buffer[1]
            i2c.write_then_readinto(self.buf, self.buf, out_end=1, in_start=0)

    def check_id(self) -> bool:
        # first check that DIDL == 0
        self.read_u16(DEVICE_ID)
        DIDL = (self.buf[0] >> 4) & ((1 << 2) - 1)      # 13-12
        if not DIDL == 0:
            return False

        # second check that DIDH == 0x121
        DIDH = self.buf[0] & ((1 << 4) - 1)             # 11-8
        DIDH = (DIDH << 8) + self.buf[1]                # add 7-0
        if not (DIDH == 0x121):
            return False

        return True

    def get_exp_msb(self, register) -> tuple:
        # read register into buffer
        self.read_u16(register)

        # separate each component
        exponent = (self.buf[0] >> 4) & ((1 << 4) - 1)  # 15-12

        result_msb = (self.buf[0] & ((1 << 4) - 1))     # 11-8
        result_msb = result_msb << 8                    # pad
        result_msb += self.buf[1]                       # add 7-0

        return exponent, result_msb

    def get_lsb_counter_crc(self, register) -> tuple:
        # read register into buffer
        self.read_u16(register)

        # separate each component
        result_lsb = self.buf[0]                        # 15-8
        counter = (self.buf[1] >> 4) & ((1 << 4) - 1)   # 7-4
        crc = self.buf[1] & ((1 << 4) - 1)              # 3-0

        return result_lsb, counter, crc

    def result_of_addr(self, just_lux) -> list:
        """
        Gets Lux value from the result register. returns lux value as a float.
        If just_lux is false the counter and crc bits will be added and a tuple of the
        3 measurements will be returned
        """

        # wait for conversion to be ready
        start_time = time.monotonic() + 1.1
        while time.monotonic() < start_time:
            if self.conversion_ready_flag:
                break
            time.sleep(0.001)

        """
        15-12: EXPONENT
        11-0: RESULT_MSB
        """
        exponent, result_msb = self.get_exp_msb(RESULT_H)

        """
        15-8: RESULT_LSB
        7-4: COUNTER
        3-0: CRC

        Calculation for the CRC bits are as follows
        E = exponent
        R = result
        C = counter
        X[0]=XOR(E[3:0],R[19:0],C[3:0]) XOR of all bits
        X[1]=XOR(C[1],C[3],R[1],R[3],R[5],R[7],R[9],R[11],R[13],R[15],R[17],R[19],E[1],E[3])
        X[2]=XOR(C[3],R[3],R[7],R[11],R[15],R[19],E[3])
        X[3]=XOR(R[3],R[11],R[19])
        """
        result_lsb, counter, crc = self.get_lsb_counter_crc(RESULT_L)

        # equations from pages 17 and 18 of datasheet
        mantissa = (result_msb << 8) + result_lsb
        adc_codes = mantissa << exponent
        lux = adc_codes * .0004375

        return lux if just_lux else lux, counter, crc

    def read_from_fifo(self, register_high, regist_low, just_lux):
        """
        15-12: EXPONENT
        11-0: RESULT_MSB
        """
        exponent, result_msb = self.get_exp_msb(register_high)

        """
        15-8: RESULT_LSB
        7-4: COUNTER
        3-0: CRC
        """
        result_lsb, counter, crc = self.get_lsb_counter_crc(regist_low)

        # equations from pages 17 and 18 of datasheet
        mantissa = (result_msb << 8) + result_lsb
        adc_codes = mantissa << exponent
        lux = adc_codes * .0004375

        return lux if just_lux else lux, counter, crc

    @property
    def lux(self) -> float:
        """
        Reads out JUST the lux value from the result register. The lux is calculated from the
        0x00 register and the 8 most significant bits of the 0x01 register.

        From the 0x00 register bits 15-12 are the EXPONENT (E), while bits 11-0 are the RESULT_MSB. From
        the 0x01 register bits 15-8 are the RESULT_LSB.

        lux is calculated via:
        lux = (((RESULT_MSB << 8) + RESULT_LSB) << EXPONENT) * 437.5E-6
        """
        return self.result_of_addr(True)

    @property
    def result(self) -> tuple:
        """
        Returns, as a tuple, the lux calculated from the register, the counter, and the crc bits

        The Lux is calculated in the same way as the lux property. Refer to the lux property function for
        a detailed description of the calculation.

        The counter will count from 0 to 15 and then restart at 0 again. It is for knowing you have
        successive measurements.

        The CRC bits are for ensuring you are recieving the proper bits over your channel. The calcuation
        for these bits is as follows:
        E = exponent bits
        R = result bits
        C = counter bits
        X[0]=XOR(E[3:0],R[19:0],C[3:0]) XOR of all bits
        X[1]=XOR(C[1],C[3],R[1],R[3],R[5],R[7],R[9],R[11],R[13],R[15],R[17],R[19],E[1],E[3])
        X[2]=XOR(C[3],R[3],R[7],R[11],R[15],R[19],E[3])
        X[3]=XOR(R[3],R[11],R[19])
        """
        return self.result_of_addr(False)

    def read_lux_FIFO(self, id: Literal[0, 1, 2]) -> float:
        """
        Reads just the lux from the FIFO<id> register identically to the lux property. Returns the
        calculated lux value as a float
        """
        channels = {
            0: (FIFO_0_H, FIFO_0_L),
            1: (FIFO_1_H, FIFO_1_L),
            2: (FIFO_2_H, FIFO_2_L)
        }
        register_h, register_l = channels[id]
        return self.read_from_fifo(register_h, register_l, True)

    def read_result_FIFO(self, id: Literal[0, 1, 2]) -> tuple:
        """
        Reads the result from the FIFO<id> register identically to the result property. Returns the
        calculated values as a tuple.
        """
        channels = {
            0: (FIFO_0_H, FIFO_0_L),
            1: (FIFO_1_H, FIFO_1_L),
            2: (FIFO_2_H, FIFO_2_L)
        }
        register_h, register_l = channels[id]
        return self.read_from_fifo(register_h, register_l, False)