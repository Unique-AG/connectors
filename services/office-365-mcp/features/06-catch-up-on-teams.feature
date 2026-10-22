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
