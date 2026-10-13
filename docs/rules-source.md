# URC 2027 rules source and verification boundary

The requirements in this repository are derived from the user-supplied **University Rover Challenge Rules 2027.pdf**, whose first page is titled **University Rover Challenge 2027 – Requirements and Guidelines**. The PDF has 15 pages. References to “p.” in these documents mean the physical PDF page counted from its title page, because printed page numbers are not present.

- SHA-256: `356549544e86041938e0d5b633cf7d0bb3875e2777f3be0d8bc676dd0734678d`
- Received and extracted in this workspace on 2026-10-13.
- PDF document title metadata: `University Rover Challenge Rules 2027`.
- No revision identifier is established for the attached bytes. The official news page announces the 2027 rules release on **2026-09-22**; this announcement does not establish the revision date of the attachment.
- This supplied PDF and the current official Q&A checked below govern the implementation. On 2026-10-13 the PDF downloaded through the official requirements page matched the attachment **byte for byte** (same SHA-256, 1,760,617 bytes, 15 pages; extracted text also identical).

The PDF was read as an attachment and is not redistributed in this repository. A teammate reviewing the matrix should use the same filename and SHA-256 or explicitly document any replacement. The digest identifies the exact reviewed bytes; it does not authenticate their publisher.

## Official source check: 2026-10-13

The PDF states on p. 1 that the URC website Q&A is applicable to the requirements and guidelines; matters not covered are decided by the URC Director. An initial attempt in this workspace failed with HTTP 403. After the network state changed, the organizer pages were fetched successfully over verified HTTPS and reviewed on **2026-10-13**:

| URL | Result | Verified content |
| --- | --- | --- |
| <https://urc.marssociety.org/> | HTTP 200 | Current landing page identifies URC 2027, June 2–5, 2027, and links its rules. |
| <https://urc.marssociety.org/home/requirements-guidelines> | HTTP 200 | Identifies “URC 2027 Requirements & Guidelines,” links the applicable Q&A and embeds `University Rover Challenge Rules 2027.pdf`. Requires a detailed WBS-format Rover Expense Report. |
| <https://urc.marssociety.org/home/requirements-guidelines/qa> | HTTP 200 | Current Q&A checked in full. Its update list reads 2026-09-15, 2026-10-03, and most recently **2026-10-11** (Autonomy Q26–27 and Q5/Q12 updates; Rover/Drone Q14–15; Equipment Q5). |
| <https://urc.marssociety.org/home/urc-news> | HTTP 200 | Announces release of the URC2027 rules on **2026-09-22**, and confirms registration, PDR, SAR and competition dates. No separate amendment notice was present in the fetched news content. |
| <https://www.marssociety.org/?s=URC+2027> | HTTP 200 | Search returned unrelated Mars Society articles; it supplies no additional governing amendment. |
| <https://drive.google.com/uc?id=1rsKkkrWkLyB8JmJG5VgD8T7EQ4WewH5A&export=download> | Initially CONNECT 403; after the relevant network update, HTTP 200 | Exact embedded download URL; redirected to the download host below. Current PDF bytes match the supplied attachment. |
| <https://drive.usercontent.google.com/download?id=1rsKkkrWkLyB8JmJG5VgD8T7EQ4WewH5A&export=download> | HTTP 200; valid PDF | SHA-256 `356549544e86041938e0d5b633cf7d0bb3875e2777f3be0d8bc676dd0734678d`; 1,760,617 bytes, 15 pages; extracted text identical to the attachment. |

The official page's embedded document open URL is <https://drive.google.com/open?id=1rsKkkrWkLyB8JmJG5VgD8T7EQ4WewH5A>. The fetched PDF bytes and extracted text match the attachment, so no PDF changes were found. The applicable differences from reading the PDF alone are the Q&A clarifications below. The organizer pages, current linked PDF and Q&A were all successfully verified on the stated check date.

## Applicable Q&A clarifications

References such as “Autonomy Q21” refer to the named section and numbered question/answer on the [official Q&A page](https://urc.marssociety.org/home/requirements-guidelines/qa), checked above. These additions matter to communications and control design:

- **Rover/Drone Q13:** Delivery and Autonomy can require travel **up to 1 km from C2**, with total distance traveled potentially exceeding 1 km. Use this clarification when sizing links and energy; do not rely on the PDF's weaker “not expected” wording.
- **Delivery Q2:** Bring **25 m cable for both rover and drone** links. Both pilots/operators stay inside C2 without course view, including avoiding a position next to a door/window that gives a view.
- **Autonomy Q21 and Q25:** Operators remain hands-off while the rover is moving autonomously, including map editing on disconnected devices. Programming is allowed while stopped between tasks and also during teleoperation; operators must be hands-off before astronaut commands. The C2 drone pilot is the sole permitted person touching controls during rover autonomy, visibly controlling only the drone. The astronaut cannot pilot it. This simulator deliberately keeps all package mutations stopped-only, a stricter software boundary than the Q&A teleoperation allowance.
- **Autonomy Q5, Q7, Q15, Q24, Q26–27:** EVA camera/microphone information can be relayed to the rover; two-way astronaut/C2 communication and relays are permitted. Assistance commands originate at the astronaut except initial approach and permitted interventions. Recognition can use any camera(s); speech may reach the rover directly or by radio. The astronaut may carry electronics in the suit but **may not deploy items** in the field. These abilities are integration gaps, not implemented audio/video or perception.
- **Autonomy Q3, Q9, Q18:** The team must establish daylight LED visibility. Flashing green is not required for Fetch/Stay/Give; Stay waits for a new command rather than reporting completion. The rover LED is sufficient for arrival at the out-of-link target; C2 arrival indication is recommended, not mandatory for 2027.
- **Autonomy Q4, Q6, Q11, Q13, Q16–17, Q20:** A first aborted objective without a previous GNSS point requires return to the start area in front of C2. Follow alone uses the command-mode scoring breakdown; mixed primary/fallback mechanisms are allowed. Gesture inputs use arm/leg/torso movements, not fingers/faces. Assistance commands follow Follow, Stay, Fetch, Come, Give order. Target coordinates are exact; terrain choice remains the team's responsibility. DEM approval/timeline is not guaranteed; GeoTIFF is only described as likely.
- **Rover/Drone Q5, Q9–11, Q14–15; Autonomy Q19, Q22:** No satellite internet; GNSS correction requires a locally provided base because there is no field internet. Public terrain datasets are allowed. Drones cannot participate in Astrobiology or Equipment Servicing. Repeaters are encouraged and count toward the applicable mass/cost budgets; drones may deploy repeaters but not mini-rovers. Human battery swaps count as interventions; vehicle-executed swaps are a separate permitted capability. Drone takeoff/landing requires permission so the judge and spotter can confirm a clear area.
- **Equipment Q2–5:** No keyboard touching under manual control; avoid touching the delicate screen. Judges reset the display for a new autonomous typing attempt. The 10-minute transition includes reweigh/measurement unless one of the stated unchanged/reduced-configuration exceptions applies. Judges may permit completion confirmation for selected poor-visibility tasks, not scoring queries; final eligible tasks are determined near competition.
- **Autonomy Q12:** Required suit clothing and wearable electronics count toward cost, not mass. Optional helmet, gloves, shoes, backpack, base layers, water, hat, sunglasses and other non-required clothing are excluded from that cost accounting clarification.

[requirements-matrix.md](requirements-matrix.md) incorporates these clarifications and maps their implementation boundaries. No code claims to enforce human hands-off behavior, astronaut command origin, live aviation procedures, or a complete scoring model.

Before a field release, recheck the linked official PDF and Q&A/news for updates after 2026-10-13, comparing any new PDF digest/text to this verified source. Record changed sources and resolve differences with the team. Earlier-year rules are not used as 2027 authority.

## How to read the claims

[requirements-matrix.md](requirements-matrix.md) distinguishes tested software behavior from manual procedures and hardware integration. A passing simulator check establishes behavior of this implementation only. It does not establish FCC authorization, FAA compliance, terrain safety, autonomous navigation competence, radio range, battery isolation, physical indicator visibility, or overall competition compliance. [hardware-gaps.md](hardware-gaps.md) lists the evidence still needed before field operation.

## Source deadlines relevant to integration

These dates are transcribed from the attachment. The official news/landing pages confirm registration, PDR, SAR and field-competition dates; recheck future organizer updates:

| Deliverable | PDF citation | Date |
| --- | --- | --- |
| Registration | §3.a.i, p. 11 | 2026-10-30 |
| Preliminary Design Review | §3.a.ii, pp. 11–12 | 2026-12-02 |
| System Acceptance Review | §3.a.iii, p. 12 | 2027-03-05 |
| Communications devices and applicable operator-license details to URC Director | §2.c.ii, p. 10 | 2027-04-30; immediately notify later changes |
| Science Plan | §1.b.i, p. 2 | 2027-05-21 |
| Final Rover Expense Report | §3.c.ii, p. 13 | 2027-05-26; updates allowed 2027-06-02 |
| Field competition | §3.a.iv, p. 12 | 2027-06-02 through 2027-06-05 |
