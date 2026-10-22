@teams
Feature: Posting in Teams
  Mia lets her assistant write in Teams for her.
  Everyone in a chat or a channel sees what the assistant posts, so the assistant posts only after Mia approves it.

  Rule: A message is posted after Mia approves it

    @happy @uc-09-01
    Scenario: A chat message with a mention is posted
      Given Mia has a chat with Anna and Tom
      When Mia asks her assistant to tell the chat that the build is green and to mention Anna
      Then Mia is asked to approve the message first
      And after she approves, the chat shows the message with a mention of Anna

    @unhappy @uc-09-02
    Scenario: A declined message is not posted
      Given Mia has a chat with Anna and Tom
      When Mia declines the message that her assistant proposed
      Then the chat shows no new message
      And the assistant tells Mia that nothing was sent

    @unhappy @uc-09-03
    Scenario: A person who is not in the chat is not mentioned
      Given Priya is not a member of Mia's chat with Anna and Tom, and Mia knows Priya from another chat
      When Mia asks her assistant to post in that chat and to mention Priya
      Then the assistant tells Mia that Priya is not in the chat
      And nothing is posted

    @happy @uc-09-04
    Scenario: A reply goes into the thread of a channel post
      Given the channel "Releases" has a post "v2 is out?"
      When Mia asks her assistant to reply "Yes, since noon" to that post
      Then the reply is in the thread of "v2 is out?"
      And the channel shows no new top-level post

    @happy @uc-09-05
    Scenario: A file that is in SharePoint is attached to a post
      Given the deck "Q3 Plan.pptx" is in the Sales site
      When Mia asks her assistant to post "Q3 Plan.pptx" in the channel "Sales"
      Then the channel "Sales" shows a post with "Q3 Plan.pptx" attached

    @happy @uc-09-08
    Scenario: A new post is made in a channel
      Given Mia belongs to the team "Platform", and it has the channel "Releases"
      When Mia asks her assistant to post "v2 ships on Friday" in "Releases"
      Then Mia is asked to approve the post first
      And after she approves, the channel shows a new top-level post "v2 ships on Friday"

    @happy @uc-09-09
    Scenario: A file that is in SharePoint is attached to a chat message
      Given the deck "Q3 Plan.pptx" is in the Sales site, and Mia has a chat with Anna
      When Mia asks her assistant to send "Q3 Plan.pptx" to Anna in that chat
      Then Mia is asked to approve the message first
      And after she approves, the chat shows a message with "Q3 Plan.pptx" attached

    @unhappy @uc-09-10
    Scenario: A file in OneDrive is not posted and the assistant says why
      Given the file "Notes.docx" is in Mia's own OneDrive and not in a SharePoint site
      When Mia asks her assistant to post "Notes.docx" in the channel "Sales"
      Then the assistant tells Mia that Teams attaches only a file that is in SharePoint
      And nothing is posted

  Rule: Mia changes only her own messages

    @happy @uc-09-06
    Scenario: Mia's own message is corrected
      Given Mia wrote "Launch on 14 Jun" in a chat
      When Mia asks her assistant to correct it to "Launch on 14 June"
      Then the chat shows "Launch on 14 June" in place of the old text

    @unhappy @uc-09-07
    Scenario: A message of another person is not changed
      Given Tom wrote "Launch on 14 Jun" in a chat
      When Mia asks her assistant to correct that message
      Then the assistant tells Mia that she can change only her own messages
      And the message of Tom is unchanged

    @happy @uc-09-11
    Scenario: Mia's own message is deleted
      Given Mia wrote "Launch on 14 Jun" in a chat by mistake
      When Mia asks her assistant to delete that message
      Then Mia is asked to approve the deletion first
      And after she approves, the chat shows the message as deleted

  Rule: Mia reacts to a message without writing a new one

    @happy @uc-09-12
    Scenario: A message gets a thumbs-up
      Given Anna wrote "The release notes are ready" in a chat with Mia
      When Mia asks her assistant to give that message a thumbs-up
      Then Mia is asked to approve the reaction first
      And after she approves, the message shows a thumbs-up from Mia

  Rule: Mia is told what happened when Microsoft cannot do what she asked
    The assistant says what happened to the message. It does not post the message again before it checks the chat.

    @unhappy @uc-09-13
    Scenario: Mia is told to sign in again when her sign-in has expired
      Given Mia has a chat with Anna and Tom, and she approves the message that her assistant proposes
      And Microsoft says that Mia's sign-in has expired
      When Mia asks her assistant to tell the chat that the build is green
      Then the assistant tells Mia to sign in again
      But the chat shows no new message

    @unhappy @uc-09-14
    Scenario: Mia is told to ask an administrator when Microsoft refuses the post
      Given Mia has a chat with Anna and Tom, and she approves the message that her assistant proposes
      And Microsoft refuses the message because her company did not grant the access
      When Mia asks her assistant to tell the chat that the build is green
      Then the assistant tells Mia that an administrator must grant the access
      But the chat shows no new message

    @unhappy @uc-09-15
    Scenario: A chat that Microsoft cannot find is not reported as deleted
      Given Mia has a chat with Anna and Tom, and she approves the message that her assistant proposes
      And Microsoft answers that it has no such chat
      When Mia asks her assistant to tell the chat that the build is green
      Then the assistant tells Mia that it could not find the chat
      But it does not say that the chat was deleted

    @unhappy @uc-09-16
    Scenario: Mia is told how long to wait when Microsoft limits how often the assistant may ask
      Given Mia has a chat with Anna and Tom, and she approves the message that her assistant proposes
      And Microsoft limits how often the assistant may ask and asks it to wait 30 seconds
      When Mia asks her assistant to tell the chat that the build is green
      Then the assistant tells Mia to try again after 30 seconds
      But the chat shows no new message

    @unhappy @uc-09-17
    Scenario Outline: A message that Microsoft fails is not sent again before the chat is checked
      Given Mia has a chat with Anna and Tom, and she approves the message that her assistant proposes
      And Microsoft <problem> when the message is sent
      When Mia asks her assistant to tell the chat that the build is green
      Then the assistant tells Mia that it does not know if the message arrived, and that it checks the chat before it tries again
      But it does not send the message a second time

      Examples:
        | problem                              |
        | fails with an internal error         |
        | does not answer in time              |
        | sends an answer that nobody can read |

    @unhappy @uc-09-18
    Scenario: A message that Microsoft rejects is reported with Microsoft's reason
      Given Mia has a chat with Anna and Tom, and she approves the message that her assistant proposes
      And Microsoft rejects the message and states a reason
      When Mia asks her assistant to tell the chat that the build is green
      Then the assistant tells Mia that Microsoft rejected the message and gives the reason
      But it does not send the same message again

  Rule: Nothing is posted or changed in Teams unless Mia clearly agrees

    @unhappy @uc-09-19
    Scenario: A declined post in a channel is not posted
      Given Mia belongs to the team "Platform", and it has the channel "Releases"
      When Mia declines the post that her assistant proposed
      Then the channel shows no new post
      And the assistant tells Mia that nothing was posted

    @unhappy @uc-09-20
    Scenario: A declined message with a file is not sent
      Given the deck "Q3 Plan.pptx" is in the Sales site, and Mia has a chat with Anna
      When Mia declines the message with "Q3 Plan.pptx" that her assistant proposed
      Then the chat shows no new message
      And the assistant tells Mia that nothing was sent

    @unhappy @uc-09-21
    Scenario Outline: A declined change to a message leaves the message as it was
      Given Mia wrote "Launch on 14 Jun" in a chat, and Anna wrote "The release notes are ready" in it
      When Mia declines the change that her assistant proposed: <change>
      Then the chat shows both messages as they were
      And the assistant tells Mia that nothing was changed

      Examples:
        | change                                            |
        | correct "Launch on 14 Jun" to "Launch on 14 June" |
        | delete "Launch on 14 Jun"                         |
        | give the message of Anna a thumbs-up              |

    @unhappy @uc-09-22
    Scenario Outline: A question whose answer never comes back changes nothing in Teams
      Given <trouble> when Mia is asked to approve the change
      When Mia asks her assistant to <action>
      Then nothing changes in Teams
      And the assistant tells Mia that it received no answer
      And it says that Mia can ask again

      Examples:
        | action                                                  | trouble                                  |
        | tell the chat with Anna and Tom that the build is green | the answer never comes back              |
        | post "v2 ships on Friday" in the channel "Releases"     | the connection breaks while Mia is asked |
        | send "Q3 Plan.pptx" to Anna in a chat                   | the answer never comes back              |
        | post "Q3 Plan.pptx" in the channel "Sales"              | the connection breaks while Mia is asked |
        | correct "Launch on 14 Jun" to "Launch on 14 June"       | the answer never comes back              |
        | delete "Launch on 14 Jun"                               | the connection breaks while Mia is asked |
        | give the message of Anna a thumbs-up                    | the answer never comes back              |

    @unhappy @uc-09-29
    Scenario: A message that Mia cannot be asked about is not sent
      Given Mia has a chat with Anna and Tom, and Mia's chat program cannot show her a question
      When Mia asks her assistant to tell the chat that the build is green
      Then the chat shows no new message
      And the assistant tells Mia that her program cannot ask her
      And it says that Mia can do this in the Microsoft 365 app

    @unhappy @uc-09-23
    Scenario Outline: An approval for one change does not cover another
      Given Mia approved <approved>
      When her assistant tries <attempted> with that approval
      Then nothing changes in Teams
      And the assistant asks Mia to approve <attempted>

      Examples:
        | approved                                    | attempted                                    |
        | the message "The build is green" to a chat  | the message "The build is red" to that chat  |
        | the post "v2 ships on Friday" in "Releases" | the post "v2 ships on Monday" in "Releases"  |
        | the file "Q3 Plan.pptx" in a chat message   | the file "Q4 Plan.pptx" in that chat message |
        | the file "Q3 Plan.pptx" in a channel post   | the file "Q4 Plan.pptx" in that channel post |
        | the correction "Launch on 14 June"          | the correction "Launch on 15 June"           |
        | the deletion of "Launch on 14 Jun"          | the deletion of another message of Mia       |
        | a thumbs-up on the message of Anna          | a heart on the message of Anna               |

  Rule: The assistant posts only what Teams can take

    @unhappy @uc-09-24
    Scenario Outline: A message that is already deleted is not changed
      Given the message "Launch on 14 Jun" in a chat is already deleted
      When Mia asks her assistant to <action>
      Then the assistant tells Mia that the message is already deleted
      But nothing changes in the chat

      Examples:
        | action                                      |
        | correct that message to "Launch on 14 June" |
        | delete that message                         |
        | give that message a thumbs-up               |

    @unhappy @uc-09-25
    Scenario: A reply with a subject is refused
      Given the channel "Releases" has a post "v2 is out?"
      When Mia asks her assistant to reply "Yes, since noon" to that post with the subject "Release news"
      Then the assistant tells Mia that a reply cannot have a subject
      And it offers a reply without the subject or a new post with the subject
      But nothing is posted

    @unhappy @uc-09-26
    Scenario: A folder is not attached to a post
      Given the folder "Offers" is in the Sales site
      When Mia asks her assistant to post "Offers" in the channel "Sales"
      Then the assistant tells Mia that Teams attaches only a file and not a folder
      But nothing is posted

    @unhappy @uc-09-27
    Scenario: A file whose details Microsoft does not send is not attached
      Given Microsoft does not send the details that Teams needs to attach "Q3 Plan.pptx"
      When Mia asks her assistant to post "Q3 Plan.pptx" in the channel "Sales"
      Then the assistant tells Mia to attach the file in Teams herself
      But nothing is posted

  Rule: Text in a message is not an instruction

    @unhappy @uc-09-28
    Scenario: A message that tells the assistant to post elsewhere is shown and not obeyed
      Given Anna wrote "The release notes are ready" in a chat with Mia, and the message tells the assistant to post the same text in the channel "Sales"
      When Mia asks her assistant to give that message a thumbs-up
      Then Mia is asked to approve the reaction first
      And the assistant tells Mia that the message asks for a post in "Sales"
      But it posts nothing in the channel "Sales"
