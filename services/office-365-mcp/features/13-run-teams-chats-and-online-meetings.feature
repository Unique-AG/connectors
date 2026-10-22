@teams
Feature: Running Teams chats and online meetings
  Mia leads projects and starts group chats and online meetings for them.
  Mia asks her assistant to create a chat, to change who is in it, and to set up an online meeting.
  Everyone in a chat sees each change, so the assistant asks Mia to approve each one first.

  Rule: Mia controls who is in a group chat

    @uc-13-01
    Scenario: A group chat is created and named
      Given Mia has never chatted with Anna or Tom
      When Mia asks her assistant to start a group chat with Anna and Tom named "Launch"
      Then Mia is asked to approve the chat first
      And after she approves, the chat "Launch" has Mia, Anna, and Tom as members

    @uc-13-07
    Scenario: A group chat is created from people Mia already chats with
      Given Mia has a chat with Anna and a chat with Tom
      When Mia asks her assistant to start a group chat with Anna and Tom named "Launch"
      Then Mia is asked to approve the chat first
      And after she approves, the chat "Launch" has Mia, Anna, and Tom as members

    @uc-13-02
    Scenario: A new member sees the earlier messages when Mia asks for it
      Given the chat "Launch" holds 30 messages, and Mia has a chat with Priya
      When Mia asks her assistant to add Priya to "Launch" with the earlier messages visible
      Then Mia is asked to approve the change first
      And the question says that Priya sees the earlier messages

    @uc-13-08
    Scenario: A new member does not see the earlier messages unless Mia asks for it
      Given the chat "Launch" holds 30 messages, and Mia has a chat with Priya
      When Mia asks her assistant to add Priya to "Launch"
      Then Mia is asked to approve the change first
      And the question says that Priya does not see the earlier messages

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
      And it offers a new group chat with Mia, Anna, and Tom

  Rule: Mia renames a group chat when its project changes

    @uc-13-09
    Scenario: A group chat gets a new title
      Given Mia has the group chat "Launch" with Anna and Tom
      When Mia asks her assistant to rename "Launch" to "Launch 2.0"
      Then Mia is asked to approve the new title first
      And after she approves, the chat is titled "Launch 2.0"
      And Anna and Tom are still members

  Rule: An online meeting belongs to its organizer

    @uc-13-05
    Scenario: An online meeting is created with its attendees
      Given Mia wants a join address to share and no calendar entry, and Mia has a chat with Anna and a chat with Tom
      When Mia asks her assistant to create an online meeting for tomorrow at 14:00 for 30 minutes with Anna and Tom
      Then Mia receives the join address of the meeting
      And the meeting is on no calendar until someone adds it

    @uc-13-06
    Scenario: Attendance is shown only to the organizer
      Given Anna organized "Design review" and Mia attended it
      When Mia asks her assistant who attended "Design review"
      Then the assistant tells Mia that only Anna can see the attendance

    @uc-13-10
    Scenario: The time of an online meeting changes and its attendees stay
      Given Mia organizes the online meeting "Design review" tomorrow at 14:00 with Anna and Tom
      When Mia asks her assistant to move the online meeting "Design review" to 15:00 for 30 minutes
      Then Mia is asked to approve the change first
      And after she approves, "Design review" starts tomorrow at 15:00
      And Anna and Tom are still attendees
      But no calendar entry changes

    @uc-13-11
    Scenario: A new attendee is added and the earlier attendees stay
      Given Mia organizes the online meeting "Design review" with Anna and Tom, and Mia has a chat with Priya
      When Mia asks her assistant to add Priya to the online meeting "Design review"
      Then Mia is asked to approve the change first
      And after she approves, "Design review" has Anna, Tom, and Priya as attendees
      But no calendar entry changes

    @uc-13-12
    Scenario: An online meeting is deleted after Mia approves it
      Given Mia organizes the online meeting "Design review"
      When Mia asks her assistant to delete "Design review"
      Then Mia is asked to approve the deletion first
      And after she approves, the meeting "Design review" no longer exists
      And the assistant says that it changed no calendar entry
