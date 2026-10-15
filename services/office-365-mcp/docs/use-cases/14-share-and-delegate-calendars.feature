@outlook-calendar
Feature: Sharing and delegating calendars
  Mia works with an executive assistant, Priya, and she shares calendars with her team.
  Mia asks her assistant to share a calendar, to act on a calendar that someone delegated to her, and to read a team calendar.

  Rule: Mia shares her own calendar and can stop sharing it

    Scenario: A colleague is given read access to a calendar
      When Mia asks her assistant to let Anna see her calendar
      Then Mia is asked to approve the share first
      And after she approves, Anna can see Mia's calendar once she accepts the invitation

    Scenario: A share is stopped
      Given Anna can see Mia's calendar
      When Mia asks her assistant to stop sharing her calendar with Anna
      Then Mia is asked to approve the change first
      And after she approves, Anna can no longer see Mia's calendar

  Rule: A delegate acts in the name of the person who delegated

    Scenario: A meeting is booked on the calendar of a manager
      Given Mia's manager Lena delegated her calendar to Mia
      When Mia asks her assistant to book "Budget review" on Lena's calendar
      Then "Budget review" is on Lena's calendar
      And the invitations to the attendees name Lena as the sender

    Scenario: A calendar without delegation is not changed
      Given Lena did not delegate her calendar to Mia
      When Mia asks her assistant to book "Budget review" on Lena's calendar
      Then the assistant tells Mia that she has no access to Lena's calendar
      And Lena's calendar is unchanged

  Rule: A team calendar shows the events of the whole team

    Scenario: The events of a team calendar are listed for a week
      Given the team "Platform" has 4 events on its calendar this week
      When Mia asks her assistant what is on the calendar of "Platform" this week
      Then the assistant lists the 4 events
