# Bill of materials

One row per part. Prices go in Notes with the currency and date.

Prices are indicative, dated 2026-10-22. They are copied from the upstream
SO-ARM100 page's EU column (Alibaba and Amazon.fr, already in EUR), not
checked in a shop. The USD figure in brackets is upstream's US-shop price for
the same part, not a conversion. Cost is per unit unless stated.

Parts marked **Confirm (#29)** are for the owner to check against what was
actually bought or received.

## Parts

| Part | Qty | Source | Notes |
|---|---|---|---|
| Feetech STS3215 servo, 7.4 V, 1/345 (C001), follower | 6 | [Alibaba](https://www.alibaba.com/product-detail/Top-Seller-Low-Cost-Feetech-STS3215_1600999461525.html) | EUR 12.2 each (USD 13.89). **Confirm (#29)**: 7.4 V or 12 V variant. |
| Feetech STS3215 servo, 7.4 V, leader, geared per table below | 6 | [Alibaba bundle of all six](https://www.alibaba.com/product-detail/6PCS-7-4V-STS3215-Servos-for_1601428584027.html) | 3 x 1/147 (C046), 2 x 1/191 (C044), 1 x 1/345 (C001). EUR 12.2 each (USD 13.89); bundle price not listed upstream. **Confirm (#29)**: the gear mix, by the C0xx label on each servo. |
| Servo bus controller board (Waveshare) | 2 | [Amazon.fr](https://www.amazon.fr/-/en/dp/B0CJ6TP3TP/) | One per arm. EUR 11.4 each (USD 10.6). **Confirm (#29)**: model and jumper position. |
| Power supply, 5 V | 2 | [Amazon.fr](https://www.amazon.fr/-/en/dp/B01HRR9GY4/) | One per arm. EUR 15.7 each (USD 10). The leader's supply is always 5 V. Only the follower's changes: 12 V, 5 A or more, if it has 12 V servos (see below). Ours (2026-10-26): leader 5 V, follower 12 V; the follower servos read `Max_Voltage_Limit` 14.0 V, so they are the 12 V variant. |
| USB-C cable (pack of 2) | 1 | [Amazon.fr](https://www.amazon.fr/dp/B07BNF842T/) | One cable per board. EUR 7 per pack (USD 7). |
| Printed arm parts (leader + follower) | 1 set | | STL in upstream SO-ARM100. **Confirm (#29)**: printed or bought. |
| Camera | | | None in the upstream BOM, no price. See Cameras. **Confirm (#29)**: which camera. |
| Table clamps (pack of 4) | 1 | [Amazon.fr](https://www.amazon.fr/Connex-COXT865210-Lot-Serre-joints-bricolage/dp/B00NA3T2CQ) | EUR 9.7 per pack (USD 9). |
| Screwdriver set (Phillips #0 and #1) | 1 | [Amazon.fr](https://www.amazon.fr/Vinabo-Magnétique-Electronique-Réparation-Informatique/dp/B0BNQBNFFJ) | EUR 9 (USD 6). Any set with #0 and #1 will do. |

Upstream totals for the 7.4 V build, EU column: EUR 226.3 for two arms
(USD 229.88), EUR 124.3 for one follower alone (USD 121.94). These sum the
rows above with upstream's clamp quantities and exclude printing, cameras and
shipping.

## Gearing per joint

The follower uses 6 x STS3215 at 1/345. The leader uses three gearings, so it
holds its own weight yet moves with little force.

| Joint | Name | Leader gear | Follower gear |
|---|---|---|---|
| 1 | Shoulder pan (base) | 1/191 | 1/345 |
| 2 | Shoulder lift | 1/345 | 1/345 |
| 3 | Elbow flex | 1/191 | 1/345 |
| 4 | Wrist flex | 1/147 | 1/345 |
| 5 | Wrist roll | 1/147 | 1/345 |
| 6 | Gripper | 1/147 | 1/345 |

Source: [LeRobot SO-101 guide](https://huggingface.co/docs/lerobot/so101).
This matches the figures in issue #28. Upstream differs only in where things
are stated: the SO-ARM100 README gives the leader's servo counts (3 x 1/147,
2 x 1/191, 1 x 1/345) but not which joint gets which; the per-joint mapping
is only in the LeRobot guide. The two sources agree on the counts.

## Servo voltage and power supply

The STS3215 comes in two voltage variants.

| Variant | Stall torque | Power supply | Used for |
|---|---|---|---|
| 7.4 V | 16.5 kg.cm at 6 V (a little less at 5 V) | 5 V | Leader (always), follower (default) |
| 12 V | 30 kg.cm | 12 V, 5 A or more | Follower only, optional |

Upstream: "The leader arm is always 7.4V for the SO101", and a 12 V follower
needs "a 12V 5A+ power supply instead of a 5V one". Upstream links a 12 V
6-servo pack on [Alibaba](https://www.alibaba.com/product-detail/6PCS-12V-30KG-STS3215-High-Torque_1601216757543.html)
and gives no price, so none is listed here.

Why the wrong PSU is dangerous (our reasoning, not upstream wording):

- 12 V into a 7.4 V servo overvolts it. That can burn out the servo
  electronics. A 5 V and a 12 V supply look
  alike and often share the same barrel plug, so they are easy to swap.
- 5 V into 12 V servos does not break them but starves them: weak torque,
  stalls and resets.
- A 12 V follower and a 7.4 V leader need different supplies. Label each
  supply and never plug the 12 V one into the leader's board.

Check the voltage printed on each supply and on each servo label before
first power-up. **Confirm (#29)**: which variant the follower servos are.

## Bus servo adapter boards

Upstream calls it the "Motor Control Board": a Waveshare bus servo adapter
([Amazon.com](https://www.amazon.com/Waveshare-Integrates-Control-Circuit-Supports/dp/B0CTMM4LWK/),
[Amazon.fr](https://www.amazon.fr/-/en/dp/B0CJ6TP3TP/)). One per arm: it
takes the servo power and talks to the computer over USB-C. The LeRobot
guide says that on a Waveshare board the two jumpers must sit on the `B`
channel (USB). A printed mounting plate exists upstream
(`WaveShare_Mounting_Plate_SO101.stl`).

## Cameras

Not part of the upstream BOM and not priced. Upstream offers printed wrist
and overhead mounts for 32x32 UVC modules, Intel RealSense D405 and
D435/D435I, and a Vinmooog webcam. Pick the camera once the owner decides
(#29).

## Sources

- [LeRobot SO-101 guide](https://huggingface.co/docs/lerobot/so101)
- [TheRobotStudio/SO-ARM100 README](https://github.com/TheRobotStudio/SO-ARM100)
