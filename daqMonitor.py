#!/usr/bin/env python3
import numpy as np
import time
import datetime
from ctypes import c_uint32
import ROOT

from DT5560Digitizer_Functions import (
    ConnectDevice, CloseDevice,
    WriteReg, ReadFifo
)
import DT5560Digitizer_RegisterFile as RF


# -------------------------------------------------------
IP_BOARD = "172.25.26.120"

CHANNELS = 32
WAVE_LEN = 40
TS_NS = 8.0  # 8 ns por sample

# ADC range
ADC_MIN = 6000
ADC_MAX = 8300
ADC_BIN = 4
NBIN_ADC = (ADC_MAX - ADC_MIN) // ADC_BIN

# Evento structure
EVENT_HEADER_WORDS = 16
WORDS_PER_SAMPLE = 16  # = 32 canales / 2
EVENT_WORDS = EVENT_HEADER_WORDS + WORDS_PER_SAMPLE * WAVE_LEN

# Lecture FIFO
TIMEOUT_MS = 200
FIFO_CHUNK = EVENT_WORDS * 2

# Events to adquire
N_EVENTS = 100   
REFRESH_EVERY = max(1, N_EVENTS // 10)  # update each 10%


# Decode ******

def decode_event(event):
    wave_data = event[EVENT_HEADER_WORDS:]
    waves = np.zeros((CHANNELS, WAVE_LEN), dtype=np.uint16)

    idx = 0
    for i in range(WAVE_LEN):
        for pair in range(WORDS_PER_SAMPLE):
            if idx >= len(wave_data):
                break

            word = wave_data[idx]
            chA = pair * 2
            chB = pair * 2 + 1

            if chA < CHANNELS:
                waves[chA, i] = word & 0xFFFF
            if chB < CHANNELS:
                waves[chB, i] = (word >> 16) & 0xFFFF

            idx += 1

    return waves


############################
def create_histos():
    h = []
    for ch in range(CHANNELS):
        H = ROOT.TH2D(
            f"h2_ch{ch}", f"ch {ch}; time, ns; amplitude, ADC",
            WAVE_LEN, 0, WAVE_LEN * TS_NS,
            NBIN_ADC, ADC_MIN, ADC_MAX
        )
        H.SetStats(False)
        h.append(H)
    return h

############################
def draw_canvas(hlist):
    c = ROOT.TCanvas("c", "DT5560 - Persistence 32ch", 1600, 900)
    c.Divide(8, 4)
    for ch in range(CHANNELS):
        c.cd(ch + 1)
        hlist[ch].Draw("*")
    c.Update()
    return c

############################

def main():

    # ROOT file
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    outname = f"acq_{timestamp}.root"
    print(f"output: {outname}")

    # ROOT I/O
    ROOT.gStyle.SetPalette(ROOT.kBird)
    ROOT.gStyle.SetOptStat(0)

    fout = ROOT.TFile(outname, "RECREATE")
    tree = ROOT.TTree("events", "DT5560 waveforms")

    # Branch 
    wave_array = np.zeros((CHANNELS, WAVE_LEN), dtype=np.uint16)
    tree.Branch("waveforms", wave_array, f"waveforms[{CHANNELS}][{WAVE_LEN}]/s")

    # Persistence
    h2 = create_histos()
    canvas = draw_canvas(h2)

    # connect
    print("Conected to DT5560...")
    err, handle = ConnectDevice(IP_BOARD)
    if err != 0:
        print("ERROR conection:", err)
        return
    print("successful Conected")

    # Config digitizer
    WriteReg(7900, RF.SCI_REG_threshold, handle)
    WriteReg(10, RF.SCI_REG_Delay, handle)
    WriteReg(WAVE_LEN, RF.SCI_REG_Digitizer_0_ACQ_LEN, handle)

    cfg_addr = RF.SCI_REG_Digitizer_0_CONFIG
    CH = CHANNELS

    def start_digitizer():
        WriteReg(2 + (CH << 8), cfg_addr, handle)
        WriteReg(0 + (CH << 8), cfg_addr, handle)
        WriteReg(1 + (CH << 8), cfg_addr, handle)

    print("Acq started")

    # acquisition 
    for iev in range(N_EVENTS):

        # progress
        if iev % REFRESH_EVERY == 0:
            pct = 100.0 * iev / N_EVENTS
            print(f"[{iev}/{N_EVENTS}]  {pct:.1f}%")

        start_digitizer()

        raw_words = []
        while len(raw_words) < EVENT_WORDS:
            buf = (c_uint32 * FIFO_CHUNK)()
            err, valid = ReadFifo(
                buf, FIFO_CHUNK,
                RF.SCI_REG_Digitizer_0_FIFOADDRESS,
                RF.SCI_REG_Digitizer_0_STATUS,
                1, TIMEOUT_MS, handle
            )

            if valid == 0:
                time.sleep(0.0005)
                continue

            arr = np.frombuffer(buf, dtype=np.uint32, count=valid)
            raw_words.extend(arr.tolist())

        data = np.array(raw_words, dtype=np.uint32)

        # Header
        hdr = np.where(data == 0xFFFFFFFF)[0]
        if hdr.size == 0:
            print("Event without header. Ignored.")
            continue

        idx = hdr[0]
        if idx + EVENT_WORDS > len(data):
            print("Event not completed. Ignored.")
            continue

        event = data[idx: idx + EVENT_WORDS]

        # Decode
        waves = decode_event(event)
        wave_array[:, :] = waves

        # histos
        for ch in range(CHANNELS):
            for s in range(WAVE_LEN):
                t = s * TS_NS
                a = waves[ch, s]
                h2[ch].Fill(t, a)
        tree.Fill()

        # Canvas
        #if iev > 0 and (iev % REFRESH_EVERY == 0):
            #canvas.Modified()
            #canvas.Update()
            #ROOT.gSystem.ProcessEvents()
        if iev > 0 and (iev % REFRESH_EVERY == 0):
            print(f"[REFRESH] Event {iev}/{N_EVENTS}  ({100*iev/N_EVENTS:.1f}%)")

            # refresh canvas
            for ch in range(CHANNELS):
                canvas.cd(ch + 1)
                h2[ch].Draw("*")

            canvas.Modified()
            canvas.Update()
            ROOT.gSystem.ProcessEvents()            


    # ---------------------------------------------------
    print("writing ROOT file")
    fout.Write()
    fout.Close()

    CloseDevice(handle)
    print("conection closed.")


if __name__ == "__main__":
    main()

