@outlook-calendar
Feature: Scheduling and answering meetings
  Mia sets up meetings and answers the invitations that she receives.
  Mia asks her assistant to find a time that suits everyone, to book it, to move it, and to answer an invitation.
  A meeting that invites other people goes out only after Mia approves it.

  Rule: Mia answers an invitation in her own words

    @working @uc-07-01
    Scenario: An invitation is accepted
      Given Anna invited Mia to "Launch review"
      When Mia asks her assistant to accept "Launch review"
      Then Anna sees Mia as accepted

    @uc-07-02
    Scenario: An invitation is declined with a note
      Given Anna invited Mia to "Launch review" on Friday
      When Mia asks her assistant to decline it with the note "I am on leave"
      Then Anna sees Mia as declined
      And Anna sees the note "I am on leave"

    @uc-07-03
    Scenario: A new time is proposed only when the organizer allows it
      Given Anna does not allow new time proposals for "Launch review"
      When Mia asks her assistant to decline it and propose Monday at 10:00
      Then the assistant tells Mia that Anna allows no new time
      And Anna sees no proposal

  Rule: Mia finds a time before she books

    @uc-07-04
    Scenario: A time is suggested when all attendees are free
      Given Anna and Tom are busy on Monday morning and free in the afternoon
      And Mia is free all day Monday
      When Mia asks her assistant for 30 minutes with Anna and Tom on Monday
      Then the assistant suggests times in the afternoon
      But it suggests no time in the morning

  Rule: A meeting is booked after Mia approves it

    @uc-07-05
    Scenario: A meeting with an online Teams meeting is booked and invitations go out
      Given Mia agreed on Monday at 14:00 with Anna and Tom
      When Mia asks her assistant to book "Launch review" with Teams
      Then Mia is asked to approve the meeting first
      And after she approves, "Launch review" is on Mia's calendar with a Teams meeting
      And Anna and Tom each receive an invitation

    @uc-07-06
    Scenario: A weekly meeting is booked as one series
      When Mia asks her assistant to book "Stand-up" every Monday for 8 weeks
      Then Mia's calendar holds 8 occurrences of "Stand-up"
      And the 8 occurrences belong to one series

    @uc-07-07
    Scenario: A meeting room is booked with the meeting
      Given the room "Maple" seats 8 and is free on Monday at 14:00
      When Mia asks her assistant to book "Workshop" with 6 people in a room
      Then the room "Maple" is invited to "Workshop"

    @known-gap @uc-07-08
    Scenario: An invitation is drafted for Mia to review before it goes out
      When Mia asks her assistant to prepare an invitation for "Board prep" without sending it
      Then Mia sees the invitation
      But nobody receives it until Mia sends it

    @known-gap @uc-07-09
    Scenario: A meeting is booked on a calendar other than the main one
      Given Mia has a second calendar named "Team"
      When Mia asks her assistant to put "Offsite" on the calendar "Team"
      Then "Offsite" is on the calendar "Team"
      But it is not on Mia's main calendar

  Rule: Only the organizer changes or cancels a meeting

    @uc-07-10
    Scenario: One date of a series moves and the other dates stay
      Given Mia organizes the weekly "Team sync" on Thursday
      When Mia asks her assistant to move next Thursday's "Team sync" to Friday
      Then only the occurrence of next Thursday moves to Friday
      But the other occurrences stay on Thursday

    @uc-07-11
    Scenario: A whole series is cancelled and attendees are told
      Given Mia organizes the weekly "Team sync" with Anna and Tom
      When Mia asks her assistant to cancel the whole series
      Then no occurrence of "Team sync" stays on Mia's calendar
      And Anna and Tom each receive a cancellation

    @uc-07-12
    Scenario: A meeting of another organizer is not changed
      Given Anna organizes "Launch review"
      When Mia asks her assistant to move "Launch review" to Friday
      Then the assistant tells Mia that only Anna can change "Launch review"
      And "Launch review" stays on its time
