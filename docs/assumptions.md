# Trip-planning assumptions

These are application decisions for the coding assessment. They are not all
direct FMCSA requirements.

- The assessment supplies current cycle usage, but not the driver's prior
  eight days of daily duty history. Natural rolling eight-day recovery cannot
  therefore be calculated.
- The assessment does not provide the driver's current 11-hour driving clock or
  14-hour duty-window state. The planner therefore assumes the trip starts after
  a qualifying 10-consecutive-hour rest, with fresh 11-hour and 14-hour clocks.
- The planner treats `70 - current_cycle_used_hours` as the available on-duty
  budget. If that budget is exhausted before the trip finishes, it schedules
  an optional 34-consecutive-hour restart and starts a fresh 70-hour budget.
- Fuel is required at least every 1,000 route miles. A fuel event is assumed
  to last 30 minutes and is recorded as on-duty, not driving.
- Pickup and dropoff each take one hour and are recorded as on-duty, not
  driving.
- A 10-consecutive-hour sleeper-berth period resets the daily driving and duty
  clocks. Split-sleeper provisions are not modeled.
- Adverse-driving provisions, short-haul exceptions, and team-driver rules are
  not modeled.
