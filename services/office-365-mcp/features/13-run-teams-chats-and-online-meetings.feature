@teams
Feature: Running Teams chats and online meetings
  Mia leads projects and starts group chats and online meetings for them.
  Mia asks her assistant to create a chat, to change who is in it, and to set up an online meeting.
  Everyone in a chat sees each change, so the assistant asks Mia to approve each one first.

  Rule: Mia controls who is in a group chat

    @uc-13-01
    Scenario: A group chat is created and named
      When Mia asks her assistant to start a group chat with Anna and Tom named "Launch"
      Then Mia is asked to approve the chat first
      And after she approves, the chat "Launch" has Mia, Anna, and Tom as members

    @uc-13-02
    Scenario: A new member sees the earlier messages only when Mia asks for it
      Given the chat "Launch" holds 30 messages
      When Mia asks her assistant to add Priya to "Launch" with the earlier messages visible
      Then Priya sees the 30 earlier messages

    @uc-13-03
    Scenario: A member is removed from a group chat
      Given the chat "Launch" has Anna, Tom, and Priya as members
      When Mia asks her assistant to remove Tom from "Launch"
      Then Mia is asked to approve the change first
      And after she approves, Tom is no longer a member of "Launch"

    @uc-13-04
    Scenario: A one-to-one chat keeps its two members
      Given Mia has a one-to-one chat with Anna
      When Mia asks her assistant to add Tom to that chat
      Then the assistant tells Mia that a one-to-one chat takes no new member

  Rule: An online meeting belongs to its organizer

    @uc-13-05
    Scenario: An online meeting is created with its attendees
      When Mia asks her assistant to create an online meeting for tomorrow at 14:00 with Anna and Tom
      Then Mia receives the join address of the meeting
      And the meeting is on no calendar until someone adds it

    @uc-13-06
    Scenario: Attendance is shown only to the organizer
      Given Anna organized "Design review" and Mia attended it
      When Mia asks her assistant who attended "Design review"
      Then the assistant tells Mia that only Anna can see the attendance
