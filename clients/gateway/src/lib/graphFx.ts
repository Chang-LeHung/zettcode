// The animation of a message: a packet that travels from the sender to each recipient, a flash on the sender, a ripple
// where it lands, a glow on the line and a pulse on the group. This holds the timeline and nothing else: it is given
// the time and a way to find a curve, and answers with what to draw, so it runs the same in a test as on the page.

import { easeInOut, curvePoint, type Curve, type Point } from "./graph";
import { reached } from "./graphData";
import type { GraphMessage, Via } from "../types";

export interface FxOptions {
  /** How long a packet takes, in milliseconds. */
  duration?: number;
  /** How many dots follow a packet. */
  trail?: number;
  /** The most packets in flight; the rest of a burst only flashes. */
  maxPackets?: number;
}

export type PulseKind = "flash" | "ripple" | "edge" | "hull";

interface Packet {
  key: string;
  message: GraphMessage;
  from: string;
  to: string;
  start: number;
}

interface Pulse {
  key: string;
  kind: PulseKind;
  /** A session id; for a hull, the group's name. */
  target: string;
  /** The other end of an edge's glow. */
  other?: string;
  via: Via;
  start: number;
  duration: number;
  grow: boolean;
}

export interface PacketFrame {
  key: string;
  message: GraphMessage;
  from: string;
  to: string;
  via: Via;
  x: number;
  y: number;
  trail: { x: number; y: number; alpha: number; scale: number }[];
}

export interface PulseFrame {
  key: string;
  kind: PulseKind;
  target: string;
  other?: string;
  via: Via;
  /** 0 to 1 over the pulse's life. */
  progress: number;
  grow: boolean;
}

export interface FxFrame {
  packets: PacketFrame[];
  pulses: PulseFrame[];
}

export class FxEngine {
  private packets: Packet[] = [];
  private pulses: Pulse[] = [];
  private counter = 0;
  readonly duration: number;
  readonly trail: number;
  readonly maxPackets: number;

  constructor(options: FxOptions = {}) {
    this.duration = options.duration ?? 900;
    this.trail = options.trail ?? 6;
    this.maxPackets = options.maxPackets ?? 60;
  }

  /** Whether anything is still moving, so the loop that calls `step` may stop when nothing is. */
  get busy(): boolean {
    return this.packets.length > 0 || this.pulses.length > 0;
  }

  get inFlight(): number {
    return this.packets.length;
  }

  clear(): void {
    this.packets = [];
    this.pulses = [];
  }

  /** Start the animation of `message` at `now` (milliseconds). With `reduced`, nothing travels: the nodes only flash. */
  spawn(message: GraphMessage, now: number, reduced = false): number {
    const sender = message.from.session_id;
    const targets = reached(message);
    const group = message.to.kind === "group" ? message.to.name : undefined;
    const add = (kind: PulseKind, target: string, start: number, duration: number, other?: string): void => {
      this.counter += 1;
      this.pulses.push({ key: `p${this.counter}`, kind, target, other, via: message.via, start, duration, grow: !reduced });
    };
    add("flash", sender, now, 520);
    if (group) add("hull", group, now, this.duration);
    let launched = 0;
    for (const to of targets) {
      if (!reduced && this.packets.length < this.maxPackets) {
        this.counter += 1;
        this.packets.push({ key: `k${this.counter}`, message, from: sender, to, start: now });
        launched += 1;
        add("ripple", to, now + this.duration, 760);
      } else {
        add("ripple", to, now, 760);
      }
      if (!group) add("edge", sender, now, reduced ? 700 : this.duration + 200, to);
    }
    return launched;
  }

  /** The picture at `now`; whatever has finished is dropped. */
  step(now: number, curveOf: (from: string, to: string) => Curve | null): FxFrame {
    this.packets = this.packets.filter((packet) => now < packet.start + this.duration);
    this.pulses = this.pulses.filter((pulse) => now < pulse.start + pulse.duration);
    const packets: PacketFrame[] = [];
    for (const packet of this.packets) {
      const curve = curveOf(packet.from, packet.to);
      if (!curve) continue;
      const raw = (now - packet.start) / this.duration;
      const head = curvePoint(curve, easeInOut(raw));
      const trail: PacketFrame["trail"] = [];
      for (let k = 1; k <= this.trail; k += 1) {
        const at: Point = curvePoint(curve, easeInOut(raw - k * 0.04));
        const along = 1 - k / (this.trail + 1);
        trail.push({ x: at.x, y: at.y, alpha: along * 0.5, scale: along });
      }
      packets.push({ key: packet.key, message: packet.message, from: packet.from, to: packet.to, via: packet.message.via, x: head.x, y: head.y, trail });
    }
    const pulses: PulseFrame[] = [];
    for (const pulse of this.pulses) {
      if (now < pulse.start) continue;
      pulses.push({
        key: pulse.key,
        kind: pulse.kind,
        target: pulse.target,
        other: pulse.other,
        via: pulse.via,
        progress: (now - pulse.start) / pulse.duration,
        grow: pulse.grow,
      });
    }
    return { packets, pulses };
  }
}
