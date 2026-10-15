@outlook-calendar
Feature: Reading the calendar
  Mia plans her day from her calendar.
  Mia asks her assistant what is on, who is coming, and when she next meets a person.
  The assistant reads Mia's own calendars and the calendars that others share with her.

  Background:
    Given Mia works in Zurich

  Rule: The assistant shows a day or a week in Mia's time zone

    Scenario: A day lists its meetings with their local times
      Given Mia has meetings at 09:00 and at 15:00 tomorrow
      When Mia asks her assistant what is on her calendar tomorrow
      Then the assistant lists both meetings with their times in Zurich time

    Scenario: A weekly meeting appears on its own date, also when one date moved
      Given Mia's "Team sync" repeats every Thursday
      And Priya moved next week's "Team sync" to Friday at 10:00
      When Mia asks her assistant what is on her calendar next week
      Then the assistant shows "Team sync" on Friday at 10:00
      But it does not show "Team sync" on Thursday

    Scenario: Overlapping meetings are named as a clash
      Given Mia has a meeting from 14:00 to 15:00 and another from 14:30 to 15:30 tomorrow
      When Mia asks her assistant whether she has a clash tomorrow
      Then the assistant names both meetings as a clash

  Rule: The assistant tells Mia who is coming

    Scenario: The attendees of a meeting are shown with their answers
      Given Mia's "Launch review" has Anna who accepted, Tom who declined, and Priya who did not answer
      When Mia asks her assistant who is coming to "Launch review"
      Then the assistant says that Anna accepted
      And it says that Tom declined
      And it says that Priya did not answer

    @known-gap
    Scenario: The next meeting with a given person is found
      Given Mia has a meeting with Tom on Friday and another on the Tuesday after
      When Mia asks her assistant for her next meeting with Tom
      Then the assistant names the meeting on Friday

  Rule: A meeting that no longer exists is reported and not invented

    @seen-failing
    Scenario: A deleted meeting is reported as gone
      Given Mia's assistant listed "Budget review" and Anna then deleted it
      When Mia asks her assistant for the details of "Budget review"
      Then the assistant tells Mia that the meeting no longer exists
