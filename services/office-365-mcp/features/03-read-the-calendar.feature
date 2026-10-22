@outlook-calendar
Feature: Reading the calendar
  Mia plans her day from her calendar.
  Mia asks her assistant what is on, who is coming, and when she next meets a person.
  The assistant reads Mia's own calendars and the calendars that others share with her.

  Background:
    Given Mia works in Zurich

  Rule: The assistant shows a day or a week in Mia's time zone

    @uc-03-01
    Scenario: A day lists its meetings with their local times
      Given Mia has meetings at 09:00 and at 15:00 tomorrow
      When Mia asks her assistant what is on her calendar tomorrow
      Then the assistant lists both meetings with their times in Zurich time

    @uc-03-02
    Scenario: A weekly meeting appears on its own date, also when one date moved
      Given Mia's "Team sync" repeats every Thursday
      And Priya moved next week's "Team sync" to Friday at 10:00
      When Mia asks her assistant what is on her calendar next week
      Then the assistant shows "Team sync" on Friday at 10:00
      But it does not show "Team sync" on Thursday

    @uc-03-03
    Scenario: Overlapping meetings are named as a clash
      Given Mia has a meeting from 14:00 to 15:00 and another from 14:30 to 15:30 tomorrow
      When Mia asks her assistant whether she has a clash tomorrow
      Then the assistant names both meetings as a clash

  Rule: The assistant tells Mia who is coming

    @uc-03-04
    Scenario: The attendees of a meeting are shown with their answers
      Given Mia organizes "Launch review" and it has Anna who accepted, Tom who declined, and Priya who did not answer
      When Mia asks her assistant who is coming to "Launch review"
      Then the assistant says that Anna accepted
      And it says that Tom declined
      And it says that Priya did not answer

    @uc-03-05
    Scenario: The next meeting with a given person is found
      Given Mia has a meeting with Tom on Friday and another on the Tuesday after
      When Mia asks her assistant for her next meeting with Tom
      Then the assistant names the meeting on Friday

  Rule: A meeting is reached from the mail that invites to it

    @uc-03-06
    Scenario: The meeting behind an invitation mail is opened
      Given Anna invited Mia to "Launch review" by mail
      When Mia asks her assistant for the details of the meeting in Anna's mail
      Then the assistant shows the time of "Launch review"
      And it shows who else is invited

  Rule: A meeting that cannot be read is reported and not invented

    @uc-03-07
    Scenario: A meeting that cannot be read is reported as unread
      Given Mia's assistant listed "Budget review" and Anna then deleted it
      When Mia asks her assistant for the details of "Budget review"
      Then the assistant tells Mia that it could not read "Budget review"
      And it does not say that the meeting was deleted
