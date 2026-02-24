import os
import ctypes
from ctypes import (
    c_int,
    c_uint32,
    c_void_p,
    POINTER,
    Structure,
    byref,
)

#  LIBRARIES ****

LIB_PATH = "/usr/local/lib/libr5560.so"

if not os.path.exists(LIB_PATH):
    raise FileNotFoundError(f"ERROR: lib not found {LIB_PATH}")

mydll = ctypes.cdll.LoadLibrary(LIB_PATH)
print("Loaded Linux library:", LIB_PATH)


#  array definition R5560_SDKLib.h *****

# enum SOCKET_TYPE { LOW_LEVEL_TCP = 0 };
SOCKET_TYPE = c_int

class tZMQEndpoint(Structure):
    _fields_ = [
        ("zmq_context",     c_void_p),
        ("zmq_pullsocket",  c_void_p),
        ("zmq_connected",   c_int),
        ("recv_blocking",   c_int),
    ]

class tR5560_Handle(Structure):
    _fields_ = [
        ("Csocket",                 c_int),
        ("connected",               c_int),
        ("__IICBASEADDRESS",        c_uint32),
        ("__IICBASEADDRESS_STATUS", c_uint32),
        ("socketType",              SOCKET_TYPE),
        ("zmq",                     POINTER(tZMQEndpoint)),
    ]

tR5560_Handle_p = POINTER(tR5560_Handle)


#  FUNCTIONS -******/*

# int R5560_ConnectTCP(char *ipaddress, uint32_t port, tR5560_Handle *handle);
mydll.R5560_ConnectTCP.argtypes = [
    ctypes.c_char_p,
    c_uint32,
    tR5560_Handle_p,
]
mydll.R5560_ConnectTCP.restype = c_int

# int NI_CloseConnection(tR5560_Handle *handle);
mydll.NI_CloseConnection.argtypes = [tR5560_Handle_p]
mydll.NI_CloseConnection.restype  = c_int

# int NI_WriteReg(uint32_t data, uint32_t address, tR5560_Handle *handle);
mydll.NI_WriteReg.argtypes = [
    c_uint32,
    c_uint32,
    tR5560_Handle_p,
]
mydll.NI_WriteReg.restype = c_int

# int NI_ReadReg(uint32_t *data, uint32_t address, tR5560_Handle *handle);
mydll.NI_ReadReg.argtypes = [
    POINTER(c_uint32),
    c_uint32,
    tR5560_Handle_p,
]
mydll.NI_ReadReg.restype = c_int

# int NI_ReadFifo(uint32_t *data, uint32_t count,
#                 uint32_t address, uint32_t fifo_status_address,
#                 int bus_mode, uint32_t timeout_ms,
#                 tR5560_Handle *handle, uint32_t *valid_data);
mydll.NI_ReadFifo.argtypes = [
    POINTER(c_uint32),   # data
    c_uint32,            # count
    c_uint32,            # address
    c_uint32,            # fifo_status_address
    c_int,               # bus_mode
    c_uint32,            # timeout_ms
    tR5560_Handle_p,     # handle
    POINTER(c_uint32),   # valid_data
]
mydll.NI_ReadFifo.restype = c_int

# (Opcional) DMA si lo necesitas más adelante
# int NI_DMA_Read(uint32_t ch, char* buffer, uint32_t max_len,
#                 uint32_t *valid_data, tR5560_Handle *handle);
mydll.NI_DMA_Read.argtypes = [
    c_uint32,
    ctypes.c_char_p,
    c_uint32,
    POINTER(c_uint32),
    tR5560_Handle_p,
]
mydll.NI_DMA_Read.restype = c_int

# helpers *******

def ConnectDevice(ip: str):
    """
    TCP connection (port 8888).
    we get (err, handle) where handle is tR5560_Handle.
    """
    handle = tR5560_Handle()
    ip_b   = ip.encode("ascii")

    print(f"Connecting to {ip} ...")
    err = mydll.R5560_ConnectTCP(ip_b, c_uint32(8888), byref(handle))
    if err == 0:
        print("OK conected.")
    else:
        print("ERROR connecting:", err)
    return err, handle


def CloseDevice(handle: tR5560_Handle):
    """
    Close connection
    """
    return mydll.NI_CloseConnection(byref(handle))


def WriteReg(value: int, address: int, handle: tR5560_Handle):
    """
    Register 32 bits
    """
    return mydll.NI_WriteReg(
        c_uint32(value),
        c_uint32(address),
        byref(handle),
    )


def ReadReg(address: int, handle: tR5560_Handle):
    """
    read register 32 bits with (err, value).
    """
    out = c_uint32(0)
    err = mydll.NI_ReadReg(
        byref(out),
        c_uint32(address),
        byref(handle),
    )
    return err, out.value


def ReadFifo(buffer, count: int, data_addr: int, status_addr: int,
             bus_mode: int, timeout_ms: int, handle: tR5560_Handle):
    """
    Read from FIFO data

    buffer:   should be (c_uint32 * N)()
    count:    max DWORDS to read
    data_addr: dir FIFO
    status_addr: dirción del registro de estado del FIFO
    bus_mode: 1 = BLOCKING, 2 = NON-BLOCKING (según firmware)
    timeout_ms: timeout de lectura
    """
    valid = c_uint32(0)
    err = mydll.NI_ReadFifo(
        buffer,
        c_uint32(count),
        c_uint32(data_addr),
        c_uint32(status_addr),
        c_int(bus_mode),
        c_uint32(timeout_ms),
        byref(handle),
        byref(valid),
    )
    return err, valid.value


