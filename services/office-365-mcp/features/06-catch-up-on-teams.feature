@teams
Feature: Catching up on Teams
  Mia misses messages and meetings in Teams.
  Mia asks her assistant which conversations need her, where a topic was discussed, and what a meeting said.
  The assistant reads only the chats, channels, and meetings that Mia herself can see.

  Rule: The assistant shows which conversations need Mia

    @uc-06-01
    Scenario: Chats with unread messages are listed with their last message
      Given Mia has 9 chats, and the last message of 3 of them is unread
      When Mia asks her assistant which chats have unread messages
      Then the assistant lists those 3 chats
      And it shows the last message and the sender of each

    @uc-06-02
    Scenario: A chat without a title is shown by its members
      Given Mia has a group chat with no title, and its members are Anna and Tom
      When Mia asks her assistant for her chats
      Then the assistant shows that chat as the chat with Anna and Tom

  Rule: The assistant finds a message in any chat or channel

    @uc-06-03
    Scenario: A topic is found in a chat and in a channel
      Given Tom wrote about the pricing change in a chat with Mia
      And Priya wrote about the pricing change in the channel "Sales"
      When Mia asks her assistant where the pricing change was discussed
      Then the assistant shows the message of Tom
      And it shows the message of Priya

    @uc-06-04
    Scenario: A channel is read with its replies
      Given the channel "Releases" has 3 posts this week and 2 older posts, and one post of this week has 4 replies
      When Mia asks her assistant what happened in "Releases" this week
      Then the assistant gives only the 3 posts of this week
      And it includes the 4 replies under their post
      And it says whether it read all posts of the channel

    @uc-06-09
    Scenario: Messages that mention Mia are found
      Given Tom mentioned Mia in a chat on Monday
      And Priya mentioned Mia in the channel "Sales" on Tuesday
      When Mia asks her assistant where people mentioned her
      Then the assistant shows the message of Tom
      And it shows the message of Priya

    @uc-06-10
    Scenario: The messages of one person in a time window are found
      Given Tom wrote in a chat yesterday and in the channel "Sales" yesterday
      And Tom also wrote in a chat last week
      When Mia asks her assistant what Tom wrote yesterday
      Then the assistant shows the 2 messages of Tom from yesterday
      But it shows no message of Tom from last week

  Rule: The assistant reads the messages of a chat

    @uc-06-11
    Scenario: The newest messages of a named chat are read
      Given Mia has the group chat "Launch" with 40 messages, and 5 of them came today
      When Mia asks her assistant what is new in "Launch"
      Then the assistant gives the 5 messages of today with their senders
      And it says that older messages exist

    @uc-06-12
    Scenario: The unread chats are read and not only listed
      Given Mia has 3 chats whose last message is unread
      When Mia asks her assistant to read what is new in those chats
      Then the assistant gives the newest messages of each of the 3 chats
      And it names the sender of each message

  Rule: The assistant tells Mia what a meeting said

    @uc-06-05
    Scenario: A transcript becomes a summary with action items
      Given the "Design review" of yesterday has a transcript where Anna and Tom speak
      When Mia asks her assistant for a summary with the action items
      Then the summary says who said what
      And it lists the action items

    @uc-06-06
    Scenario: A transcript of three hours is read to its end
      Given the transcript of a meeting runs for three hours and ends with a decision
      When Mia asks her assistant for the decisions of that meeting
      Then the assistant names the decision from the end of the transcript

    @uc-06-07
    Scenario: A meeting without a transcript is reported
      Given nobody turned on the transcript in "Weekly sync"
      When Mia asks her assistant for a summary of "Weekly sync"
      Then the assistant tells Mia that no transcript exists

  Rule: A recording is described and never handed over

    @uc-06-08
    Scenario: The assistant describes a recording and does not give it
      Given "Design review" was recorded and runs for 52 minutes
      When Mia asks her assistant for the recording
      Then the assistant says that the recording exists and runs for 52 minutes
      And it says who may download it
      But it does not give the recording itself

  Rule: The assistant reaches the right meeting and says what blocks it

    @uc-06-13
    Scenario: The transcript of one date of a recurring meeting is read
      Given "Weekly sync" met on 5 October and on 12 October, and both meetings have a transcript
      When Mia asks her assistant for a summary of "Weekly sync" of 5 October
      Then the summary comes from the meeting of 5 October
      But it uses nothing from the meeting of 12 October

    @uc-06-14
    Scenario: A transcript that the company does not allow is reported as refused
      Given the Teams administrator of Mia's company did not allow access to transcripts
      And "Design review" of yesterday was transcribed
      When Mia asks her assistant for a summary of "Design review"
      Then the assistant tells Mia that an administrator must allow access to transcripts
      But it does not say that no transcript exists

    @uc-06-15
    Scenario: A meeting from the calendar is summarized from its transcript
      Given "Budget review" is on Mia's calendar and it has a transcript
      And Mia has no meeting chat for "Budget review"
      When Mia asks her assistant for a summary of "Budget review" from her calendar
      Then the assistant gives the summary of the transcript
