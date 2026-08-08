from __future__ import annotations

import argparse
import json
import sys
import struct

import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst, GLib


def build_pipeline(port: int) -> str:
    return (
        f'udpsrc port={port} '
        '! application/x-rtp,media=video,encoding-name=H264,payload=96 '
        '! rtph264depay '
        '! avdec_h264 '
        '! videoconvert '
        '! video/x-raw,format=BGR '
        '! appsink drop=true sync=false max-buffers=1 name=sink'
    )


def main() -> int:
    Gst.init(None)
    parser = argparse.ArgumentParser(description='Low-latency UDP H264 bridge helper')
    parser.add_argument('--port', type=int, required=True)
    args = parser.parse_args()

    pipeline = Gst.parse_launch(build_pipeline(args.port))
    sink = pipeline.get_by_name('sink')
    pipeline.set_state(Gst.State.PLAYING)

    # Wait for the pipeline to actually start receiving data
    bus = pipeline.get_bus()
    got_preroll = False
    while True:
        msg = bus.timed_pop_filtered(
            10 * Gst.SECOND,
            Gst.MessageType.ERROR | Gst.MessageType.EOS | Gst.MessageType.STATE_CHANGED,
        )
        if msg is None:
            # Timeout - no data received
            print(json.dumps({'error': f'timeout waiting for UDP data on port {args.port}'}), flush=True)
            pipeline.set_state(Gst.State.NULL)
            return 1
        if msg.type == Gst.MessageType.ERROR:
            err, debug = msg.parse_error()
            print(json.dumps({'error': f'GStreamer error: {err.message}'}), flush=True)
            pipeline.set_state(Gst.State.NULL)
            return 1
        if msg.type == Gst.MessageType.EOS:
            print(json.dumps({'error': 'unexpected EOS'}), flush=True)
            pipeline.set_state(Gst.State.NULL)
            return 1
        if msg.type == Gst.MessageType.STATE_CHANGED:
            if msg.src == pipeline:
                parse = msg.parse_state_changed()
                if parse.newstate >= Gst.State.PLAYING:
                    got_preroll = True
                    break

    # Pull the first sample to get dimensions
    sample = sink.emit('pull-sample')
    if sample is None:
        print(json.dumps({'error': f'failed to read first frame from UDP port {args.port}'}), flush=True)
        pipeline.set_state(Gst.State.NULL)
        return 1

    buf = sample.get_buffer()
    caps = sample.get_caps()
    struct = caps.get_structure(0)
    width = struct.get_value('width')
    height = struct.get_value('height')

    success, map_info = buf.map(Gst.MapFlags.READ)
    if not success:
        print(json.dumps({'error': 'failed to map buffer'}), flush=True)
        pipeline.set_state(Gst.State.NULL)
        return 1
    frame_data = bytes(map_info.data)
    buf.unmap(map_info)

    channels = 3
    print(json.dumps({'width': width, 'height': height, 'channels': channels}), flush=True)
    sys.stdout.buffer.write(frame_data)
    sys.stdout.buffer.flush()

    # Continue streaming frames
    try:
        while True:
            sample = sink.emit('pull-sample')
            if sample is None:
                break
            buf = sample.get_buffer()
            success, map_info = buf.map(Gst.MapFlags.READ)
            if not success:
                break
            sys.stdout.buffer.write(bytes(map_info.data))
            sys.stdout.buffer.flush()
            buf.unmap(map_info)
    except (BrokenPipeError, IOError):
        pass
    finally:
        pipeline.set_state(Gst.State.NULL)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
