@teams
Feature: Posting in Teams
  Mia lets her assistant write in Teams for her.
  Everyone in a chat or a channel sees what the assistant posts, so the assistant posts only after Mia approves it.

  Rule: A message is posted after Mia approves it

    @uc-09-01
    Scenario: A chat message with a mention is posted
      Given Mia has a chat with Anna and Tom
      When Mia asks her assistant to tell the chat that the build is green and to mention Anna
      Then Mia is asked to approve the message first
      And after she approves, the chat shows the message with a mention of Anna

    @uc-09-02
    Scenario: A declined message is not posted
      Given Mia has a chat with Anna and Tom
      When Mia declines the message that her assistant proposed
      Then the chat shows no new message

    @uc-09-03
    Scenario: A person who is not in the chat is not mentioned
      Given Priya is not a member of Mia's chat with Anna and Tom, and Mia knows Priya from another chat
      When Mia asks her assistant to post in that chat and to mention Priya
      Then the assistant tells Mia that Priya is not in the chat
      And nothing is posted

    @uc-09-04
    Scenario: A reply goes into the thread of a channel post
      Given the channel "Releases" has a post "v2 is out?"
      When Mia asks her assistant to reply "Yes, since noon" to that post
      Then the reply is in the thread of "v2 is out?"
      And the channel shows no new top-level post

    @uc-09-05
    Scenario: A file that is in SharePoint is attached to a post
      Given the deck "Q3 Plan.pptx" is in the Sales site
      When Mia asks her assistant to post "Q3 Plan.pptx" in the channel "Sales"
      Then the channel "Sales" shows a post with "Q3 Plan.pptx" attached

    @uc-09-08
    Scenario: A new post is made in a channel
      Given Mia belongs to the team "Platform", and it has the channel "Releases"
      When Mia asks her assistant to post "v2 ships on Friday" in "Releases"
      Then Mia is asked to approve the post first
      And after she approves, the channel shows a new top-level post "v2 ships on Friday"

    @uc-09-09
    Scenario: A file that is in SharePoint is attached to a chat message
      Given the deck "Q3 Plan.pptx" is in the Sales site, and Mia has a chat with Anna
      When Mia asks her assistant to send "Q3 Plan.pptx" to Anna in that chat
      Then Mia is asked to approve the message first
      And after she approves, the chat shows a message with "Q3 Plan.pptx" attached

    @uc-09-10
    Scenario: A file in OneDrive is not posted and the assistant says why
      Given the file "Notes.docx" is in Mia's own OneDrive and not in a SharePoint site
      When Mia asks her assistant to post "Notes.docx" in the channel "Sales"
      Then the assistant tells Mia that Teams attaches only a file that is in SharePoint
      And nothing is posted

  Rule: Mia changes only her own messages

    @uc-09-06
    Scenario: Mia's own message is corrected
      Given Mia wrote "Launch on 14 Jun" in a chat
      When Mia asks her assistant to correct it to "Launch on 14 June"
      Then the chat shows "Launch on 14 June" in place of the old text

    @uc-09-07
    Scenario: A message of another person is not changed
      Given Tom wrote "Launch on 14 Jun" in a chat
      When Mia asks her assistant to correct that message
      Then the assistant tells Mia that she can change only her own messages
      And the message of Tom is unchanged

    @uc-09-11
    Scenario: Mia's own message is deleted
      Given Mia wrote "Launch on 14 Jun" in a chat by mistake
      When Mia asks her assistant to delete that message
      Then Mia is asked to approve the deletion first
      And after she approves, the chat shows the message as deleted

  Rule: Mia reacts to a message without writing a new one

    @uc-09-12
    Scenario: A message gets a thumbs-up
      Given Anna wrote "The release notes are ready" in a chat with Mia
      When Mia asks her assistant to give that message a thumbs-up
      Then Mia is asked to approve the reaction first
      And after she approves, the message shows a thumbs-up from Mia
