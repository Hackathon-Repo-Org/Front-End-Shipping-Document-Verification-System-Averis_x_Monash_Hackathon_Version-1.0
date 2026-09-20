# UI review — findings

Fill this in while clicking. Anything you write here gets fixed before deploy; an
empty line means "not checked", which is different from "fine".

Local: <http://localhost:5173> · passcode `averis2026` · set a reviewer name first
(button, top right) or every write will be refused.

Mark each: **OK** / **BROKEN** / **AWKWARD** — "awkward" is the most useful one,
because it is the category nobody reports and the one that decides whether a tool
gets used twice.

---

### 1. The queue contains only actionable items
`/queue` should hold work, not correspondence. The ~56 awaiting-documents records
(a shipper saying the draft is coming) must NOT be in it.

- Verdict:
- Notes:

### 2. Evidence opens at the right line
Click any value on a detail screen. The drawer should open the document it was read
from, scrolled to and highlighting the exact line.

- Verdict:
- Notes:

### 3. A decision applies instantly and survives reload
Confirm or correct something. The status should change with no spinner and no
re-run. Then hard-reload the page — it must still be there.

- Verdict:
- Notes:

### 4. Keyboard navigation works
In `/queue`: `J`/`K` move, `Enter` opens, `A` confirms, `C` corrects to the SI
value, `E` clears, `R` retries, `N` jumps to the next undecided, `Esc` closes.

- Verdict:
- Notes:

### 5. Read vs inferred is visible
A value the system *inferred* must never look like one it *read*. Look for the note
under a value where it was resolved by reference (`SAME AS CONSIGNEE`) or pre-filled
by OCR.

- Verdict:
- Notes:

### 6. A mismatch row is self-explanatory
Show a colleague one `MISMATCH` row with no preamble. Can they say what is wrong and
which document is wrong, without asking you?

- Verdict:
- Notes:

### 7. Usable at phone width
Narrow the window to ~390px, or open it on a phone. Nav, tables and the evidence
drawer should all still work. This is how a judge will open it.

- Verdict:
- Notes:

### 8. Verdicts readable without colour
Every verdict should carry an icon as well as a colour. Check in greyscale, or just
cover the colour with your thumb.

- Verdict:
- Notes:

### 9. No internal vocabulary leaked to the screen
The UI should show external spellings only: `missing_value`, not `err_no_value`;
`Needs review`, not `escalated`; `Cannot determine`, not `cannot_determine`.

- Verdict:
- Notes:

### 10. Proposals are judgeable from the evidence shown
`/proposals`. For each one, is there enough on screen to approve or reject WITHOUT
opening the source document? Especially `NEW NO -> notify_party`, where the value is
a street address — the rejection should be obvious.

- Verdict:
- Notes:

---

## Anything else

Wording, ordering, what you expected to be somewhere and was not, anything that made
you pause:

-
-

## Cut list, if time runs out

In this order: bulk actions, run-from-UI, audit view. **Not** the evidence viewer,
**not** keyboard navigation.
