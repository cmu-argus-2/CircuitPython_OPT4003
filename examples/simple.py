import board
from OPT4003 import OPT4003

i2c = board.I2C()

opt = OPT4003(i2c, conversion_time=10, operating_mode=3)

while True:
    print(f"{opt.lux}")
