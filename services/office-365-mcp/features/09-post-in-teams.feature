@teams
Feature: Posting in Teams
  Mia lets her assistant write in Teams for her.
  Everyone in a chat or a channel sees what the assistant posts, so the assistant posts only after Mia approves it.

  Rule: A message is posted after Mia approves it

    Scenario: A chat message with a mention is posted
      Given Mia has a chat with Anna and Tom
      When Mia asks her assistant to tell the chat that the build is green and to mention Anna
      Then Mia is asked to approve the message first
      And after she approves, the chat shows the message with a mention of Anna

    Scenario: A declined message is not posted
      Given Mia has a chat with Anna and Tom
      When Mia declines the message that her assistant proposed
      Then the chat shows no new message

    Scenario: A person who is not in the chat is not mentioned
      Given Priya is not a member of Mia's chat with Anna and Tom
      When Mia asks her assistant to post in that chat and to mention Priya
      Then the assistant tells Mia that Priya is not in the chat
      And nothing is posted

    Scenario: A reply goes into the thread of a channel post
      Given the channel "Releases" has a post "v2 is out?"
      When Mia asks her assistant to reply "Yes, since noon" to that post
      Then the reply is in the thread of "v2 is out?"
      And the channel shows no new top-level post

    Scenario: A file that is in SharePoint is attached to a post
      Given the deck "Q3 Plan.pptx" is in the Sales site
      When Mia asks her assistant to post "Q3 Plan.pptx" in the channel "Sales"
      Then the channel "Sales" shows a post with "Q3 Plan.pptx" attached

  Rule: Mia changes only her own messages

    Scenario: Mia's own message is corrected
      Given Mia wrote "Launch on 14 Jun" in a chat
      When Mia asks her assistant to correct it to "Launch on 14 June"
      Then the chat shows "Launch on 14 June" in place of the old text

    Scenario: A message of another person is not changed
      Given Tom wrote "Launch on 14 Jun" in a chat
      When Mia asks her assistant to correct that message
      Then the assistant tells Mia that she can change only her own messages
      And the message of Tom is unchanged
