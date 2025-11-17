#!/usr/bin/env python3
import numpy as np
import time
import datetime
from ctypes import c_uint32
import ROOT
from array import array

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

# structure
EVENT_HEADER_WORDS = 16
WORDS_PER_SAMPLE = 16  # = 32 canales / 2
EVENT_WORDS = EVENT_HEADER_WORDS + WORDS_PER_SAMPLE * WAVE_LEN

# Lecture FIFO
TIMEOUT_MS = 200
FIFO_CHUNK = EVENT_WORDS * 2

# Events to adquire
N_EVENTS = 100   
REFRESH_EVERY = max(1, N_EVENTS // 10)  # update each 10%


# -------------------------------------------------------
# Decode
# -------------------------------------------------------
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


# -------------------------------------------------------
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


# -------------------------------------------------------
def draw_canvas(hlist):
    c = ROOT.TCanvas("c", "DT5560 - Persistence 32ch", 1600, 900)
    c.Divide(8, 4)
    for ch in range(CHANNELS):
        c.cd(ch + 1)
        hlist[ch].Draw("*")
    c.Update()
    return c


# -------------------------------------------------------
def main():

    # ROOT file
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    outname = f"acq_{timestamp}.root"
    print(f"Archivo de salida: {outname}")

    # ROOT I/O
    ROOT.gStyle.SetPalette(ROOT.kBird)
    ROOT.gStyle.SetOptStat(0)

    fout = ROOT.TFile(outname, "RECREATE")
    tree = ROOT.TTree("events", "DT5560 waveforms")
    #event_time_s = array('L', [0])
    event_time_us = array('Q', [0]) 

    # Branch 
    #tree.Branch("event_time_s", event_time_s, "event_time_s/l")
    tree.Branch("event_time_us", event_time_us, "event_time_us/l")
    wave_array = np.zeros((CHANNELS, WAVE_LEN), dtype=np.uint16)
    tree.Branch("waveforms", wave_array, f"waveforms[{CHANNELS}][{WAVE_LEN}]/s")

    # Persistence
    h2 = create_histos()
    canvas = draw_canvas(h2)
    
    # Amplitude
    h1_min = []
    ADC_MIN = 6200
    ADC_MAX = 8200
    NBIN_MINHIST = (ADC_MAX - ADC_MIN) // 8 

    canvas_min = ROOT.TCanvas("canvas_min", "min amplitud", 1200, 800)
    canvas_min.Divide(8, 4)

    #fill
    for ch in range(CHANNELS):
        h = ROOT.TH1D(
            f"h1_min_ch{ch}",
            f"Min ADC ch {ch}; Min amplitude; Counts",
            NBIN_MINHIST, ADC_MIN, ADC_MAX
        )
        h1_min.append(h)
 

    # connect
    print("Conectando al DT5560...")
    err, handle = ConnectDevice(IP_BOARD)
    if err != 0:
        print("ERROR de conexión:", err)
        return
    print("Conectado correctamente")

    # Config digitizer
    WriteReg(7800, RF.SCI_REG_threshold, handle)
    WriteReg(10, RF.SCI_REG_Delay, handle)
    WriteReg(WAVE_LEN, RF.SCI_REG_Digitizer_0_ACQ_LEN, handle)

    cfg_addr = RF.SCI_REG_Digitizer_0_CONFIG
    CH = CHANNELS

    def start_digitizer():
        WriteReg(2 + (CH << 8), cfg_addr, handle)
        WriteReg(0 + (CH << 8), cfg_addr, handle)
        WriteReg(1 + (CH << 8), cfg_addr, handle)

    print("starting adquisition")

    # ---------------------------------------------------
    # adquirir
    # ---------------------------------------------------
    for iev in range(N_EVENTS):

        # progreso
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

        # Buscar header
        hdr = np.where(data == 0xFFFFFFFF)[0]
        if hdr.size == 0:
            print("event corrupted")
            continue

        idx = hdr[0]
        if idx + EVENT_WORDS > len(data):
            print("event corrupted.")
            continue

        event = data[idx: idx + EVENT_WORDS]

        # Decode
        waves = decode_event(event)
        wave_array[:, :] = waves

        # TH2D
        for ch in range(CHANNELS):
            for s in range(WAVE_LEN):
                t = s * TS_NS
                a = waves[ch, s]
                h2[ch].Fill(t, a)

        # TH1D
        for ch in range(CHANNELS):
            min_val = np.min(waves[ch])
            h1_min[ch].Fill(min_val)
        

        now = datetime.datetime.utcnow()
        #ts_us = int(now.timestamp() * 1e6)
        #event_time_s[0] = int(now.timestamp()) 
        event_time_us[0] = int(now.timestamp() * 1e6)
        tree.Fill()
        # updateCanvas
        if iev > 0 and (iev % REFRESH_EVERY == 0):
            print(f"[REFRESH] Evento {iev}/{N_EVENTS}  ({100*iev/N_EVENTS:.1f}%)")

            # each hist in its pad
            for ch in range(CHANNELS):
                canvas.cd(ch + 1)
                h2[ch].Draw("*")

            canvas.Modified()
            canvas.Update()
            ROOT.gSystem.ProcessEvents()
            for ch in range(CHANNELS):
                canvas_min.cd(ch + 1)
                ROOT.gStyle.SetOptStat(1110)
                h1_min[ch].SetStats(1)
                h1_min[ch].Draw("hist")
                ROOT.gPad.SetLogy(1)
                #ROOT.gPad.Update()

            canvas_min.Modified()
            canvas_min.Update()
            ROOT.gSystem.ProcessEvents()            


    # ---------------------------------------------------
    print("saving ROOTfile...")
    for h in h2:
        h.Write()    
    for h in h1_min:
        h.Write()  
    tree.Write()    
    fout.Write()
    fout.Close()

    CloseDevice(handle)
    print("Close")


if __name__ == "__main__":
    main()


