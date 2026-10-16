# office-365-mcp use cases

!!! danger "Documentation Disclaimer"
    This feature is `EXPERIMENTAL` and under active development. It may change significantly, be
    discontinued, or have breaking changes without notice.

## Overview

This page shows what people ask an assistant to do when office-365-mcp connects it to Microsoft 365.
The examples follow Mia. Mia works with an assistant that reaches her mail, her calendar, her files,
Microsoft Teams, and her notes.

The examples come from how people use the server and from what its tools can do. A part named "Not
supported yet" lists what people ask for and what the server cannot do today. For the tools behind
the examples, read the page for office-365-mcp.

## Rules for every example

- The assistant sees only what Mia can see in Microsoft 365.
- The assistant asks Mia to approve each change that other people can see, such as a message, an
  invitation, or a share.
- The assistant sends no mail before Mia approves the draft.
- The assistant erases no mail and no file for good. A delete moves the item to Deleted Items or to
  the recycle bin. OneNote has no recycle bin, so the assistant asks Mia before it erases a page.

<!-- use-cases:begin -->

## Mail

### Finding and reading mail

Mia receives far more mail than she can read. Mia asks her assistant to find messages, to read one in full with its attachments, and to follow a whole conversation. The assistant reads Mia's own mailbox, and a shared mailbox when Mia has access to it.

#### The assistant finds a message from what Mia remembers about it

**Unread mail since yesterday is listed**

- **Given** Mia received 6 messages since yesterday morning, and 2 of them are unread
- **When** Mia asks her assistant which messages since yesterday are unread
- **Then** the assistant lists the 2 unread messages
- **But** it does not list the 4 messages that Mia read

**A message is found by sender, subject, and attachment together**

- **Given** Brightway sent "March invoice" with a PDF, and sent "March newsletter" with no attachment
- **When** Mia asks her assistant for the March invoice from Brightway that has a PDF
- **Then** the assistant shows "March invoice"
- **But** it does not show "March newsletter"

**A time window narrows the result**

- **Given** Anna sent Mia one message in February, one in March, and one in April
- **When** Mia asks her assistant for the messages that Anna sent in March
- **Then** the assistant shows only the March message

**Flagged mail is listed**

- **Given** Mia flagged 2 messages for follow-up and did not flag 5 others
- **When** Mia asks her assistant which messages she flagged
- **Then** the assistant lists the 2 flagged messages

**A result that may be incomplete says so**

- **Given** 300 messages mention "invoice"
- **When** Mia asks her assistant for every message that mentions "invoice"
- **Then** the assistant shows the newest messages
- **And** it tells Mia that more matching messages may exist

#### The assistant reads a message and its attachments

**A message is read in full and its attachments are named**

- **Given** Anna sent "Contract draft" with the attachment "Draft v2.docx" of 80 KB
- **When** Mia asks her assistant to read "Contract draft"
- **Then** the assistant gives the full text of the message
- **And** it names "Draft v2.docx" with its size

**The content of an attachment answers a question**

- **Given** Anna attached a 2 MB Excel workbook with a total of 4,200 in its last row
- **When** Mia asks her assistant for the total in the last row of that workbook
- **Then** the assistant answers 4,200

**An attachment above 10 MB is refused**

- **Given** Anna attached a 12 MB PDF
- **When** Mia asks her assistant to read that PDF
- **Then** the assistant tells Mia that the attachment is too large to read

#### The assistant follows a conversation from first message to last

**A decision is found in a long conversation**

- **Given** a conversation of 5 messages between Mia, Anna, and Tom ends with a decision to launch on 14 June
- **When** Mia asks her assistant what the conversation decided
- **Then** the assistant answers that the launch is on 14 June

#### A shared mailbox is read only with Mia's access

**Unread mail of a shared mailbox is listed**

- **Given** Mia has access to the shared mailbox "support", which holds 3 unread messages
- **When** Mia asks her assistant for the unread messages in "support"
- **Then** the assistant lists the 3 unread messages of "support"
- **But** it does not list messages of Mia's own mailbox

**A mailbox without access is refused**

- **Given** Mia has no access to the shared mailbox "finance"
- **When** Mia asks her assistant for the unread messages in "finance"
- **Then** the assistant tells Mia that she has no access to "finance"

### Drafting and sending mail

Mia lets her assistant write mail for her. The assistant leaves each message as a draft for Mia to read, and sends it only after Mia approves.

#### A draft goes to the real address of the right person

**A draft is addressed to the address of the named person**

- **Given** Anna Meier works in Legal and has the address "anna.meier@example.com"
- **When** Mia asks her assistant to draft a note to Anna Meier that asks for the contract by Friday
- **Then** the draft is addressed to "anna.meier@example.com"
- **And** the draft asks for the contract by Friday

**Two people with one name lead to a question**

- **Given** Anna Meier in Legal has the address "anna.meier@example.com"
- **And** Anna Meier in Sales has the address "anna.meier.sales@example.com"
- **When** Mia asks her assistant to draft a note to Anna Meier
- **Then** the assistant asks Mia which Anna Meier she means
- **But** it does not create the draft yet

**A person who is away is announced before the draft is sent**

- **Given** Anna has an automatic reply turned on
- **When** Mia asks her assistant whether Anna is away
- **Then** the assistant tells Mia the text of the automatic reply of Anna

#### A draft changes until Mia approves it

**A draft is shortened in place**

- **Given** Mia has a draft to Anna with 4 paragraphs
- **When** Mia asks her assistant to make the draft shorter
- **Then** the same draft has fewer words
- **But** Mia's mailbox holds no second draft

**A person is not both addressed and copied**

- **Given** Mia has a draft addressed to Tom
- **When** Mia asks her assistant to copy Tom on the draft as well
- **Then** the assistant tells Mia that Tom is already on the draft

#### Nothing is sent without Mia's approval

**An approved draft is sent**

- **Given** Mia read her draft to Anna
- **When** Mia approves that the draft is sent
- **Then** the message is in Mia's sent items
- **And** Anna receives it once

**A declined draft stays a draft**

- **Given** Mia read her draft to Anna
- **When** Mia declines that the draft is sent
- **Then** Anna receives nothing
- **And** the draft is still in Mia's drafts

**A draft that changed after the question is not sent**

- **Given** Mia was asked to approve a draft to Anna
- **And** the text of the draft changed after that question
- **When** Mia approves
- **Then** Anna receives nothing
- **And** the assistant tells Mia that the draft changed

#### A reply keeps the conversation

**A reply to everyone lists every other person**

- **Given** Anna wrote to Mia, Tom, and Priya
- **When** Mia asks her assistant for a reply to everyone
- **Then** the draft is addressed to Anna, Tom, and Priya
- **But** it is not addressed to Mia

**A forward carries the original attachments**

- **Given** Anna sent Mia "Contract draft" with the attachment "Draft v2.docx"
- **When** Mia asks her assistant to forward "Contract draft" to Tom
- **Then** the draft to Tom holds "Draft v2.docx"

#### Not supported yet

- A new file is attached to a draft

### Organizing the mailbox

Mia keeps her mailbox in order with folders, categories, and inbox rules. Mia asks her assistant to file, mark, and sort mail in bulk, and to set up rules that do it for her later. The assistant erases no mail for good. A delete moves mail to Deleted Items.

#### A batch of messages is filed whole or not at all

**A batch is filed in one folder**

- **Given** Mia has 8 newsletters from last month in her inbox
- **When** Mia asks her assistant to file them in the folder "Newsletters"
- **Then** all 8 newsletters are in "Newsletters"
- **And** her inbox holds none of them

**A batch is marked in one step**

- **Given** Mia has 8 newsletters from last month in her inbox
- **When** Mia asks her assistant to `<action>` all 8 newsletters
- **Then** all 8 newsletters `<result>`

| action | result |
| --- | --- |
| mark as read | are marked as read |
| flag for follow-up | are flagged for follow-up |
| put the category "Reading" on | carry the category "Reading" |

**A batch with one unidentified message moves nothing**

- **Given** Mia named 5 messages by their subjects only
- **And** the assistant cannot identify one of the 5 exactly
- **When** the assistant files the 5 messages in "Archive"
- **Then** no message is moved
- **And** the assistant identifies all 5 messages before it tries again

**A delete moves mail to Deleted Items**

- **Given** Mia has 3 old messages from a vendor
- **When** Mia asks her assistant to delete them
- **Then** the 3 messages are in Deleted Items
- **But** none of them is erased for good

**A change in a shared mailbox needs Mia's approval**

- **Given** Mia has access to the shared mailbox "support"
- **When** Mia asks her assistant to file a message of "support" in its folder "Handled"
- **Then** Mia is asked to approve the change first
- **And** the message stays where it is until she approves

#### Mia keeps her folders as she names them

**A folder is created inside another folder**

- **Given** Mia has the folder "Projects"
- **When** Mia asks her assistant to create the folder "Alpha" inside "Projects"
- **Then** "Projects" holds the folder "Alpha"

**A folder is renamed and keeps its mail**

- **Given** the folder "Old" holds 40 messages
- **When** Mia asks her assistant to rename "Old" to "Archive 2025"
- **Then** the folder "Archive 2025" holds the 40 messages

**A folder moves to Deleted Items only after Mia approves**

- **Given** the folder "Temp" holds 5 messages and a subfolder
- **When** Mia asks her assistant to delete "Temp"
- **Then** Mia is asked to approve the delete first
- **And** after she approves, "Temp" with all of its content is in Deleted Items

**A built-in folder is never renamed or deleted**

- **When** Mia asks her assistant to delete the folder "Inbox"
- **Then** the assistant tells Mia that Outlook keeps "Inbox" for every mailbox
- **And** the folder "Inbox" is unchanged

#### A category names a kind of mail across all folders

**A new category is created and put on mail**

- **Given** Mia has 4 unread messages from her manager
- **When** Mia asks her assistant to create the red category "Follow-up Q4" and put it on those messages
- **Then** the category "Follow-up Q4" exists and is red
- **And** the 4 messages carry it

#### An inbox rule acts on new mail without Mia

**A rule files mail from one sender**

- **When** Mia asks her assistant for a rule that moves mail from "billing@example.com" to "Finance"
- **Then** Mia's rules include a rule with that sender and that folder
- **And** new mail from "billing@example.com" arrives in "Finance"

**An old rule is turned off and stays in the list**

- **Given** Mia has the rule "Receipts"
- **When** Mia asks her assistant to turn off "Receipts"
- **Then** "Receipts" is still in Mia's rules
- **But** it no longer acts on new mail

**A rule that forwards mail needs approval that names every address**

- **When** Mia asks her assistant for a rule that forwards mail from "ceo@example.com" to Anna and Tom
- **Then** Mia is asked to approve the rule first
- **And** the question names the addresses of Anna and Tom

**A rule is erased only after Mia approves**

- **Given** Mia has the rule "Receipts"
- **When** Mia asks her assistant to erase "Receipts"
- **Then** Mia is asked to approve the erase first
- **And** after she approves, "Receipts" is no longer in her rules

**A rule never erases mail for good**

- **When** Mia asks her assistant for a rule that deletes mail from "spam@example.com"
- **Then** new mail from "spam@example.com" arrives in Deleted Items
- **But** none of it is erased for good

### Mailbox preferences

Mia sets how her mailbox behaves while she is away and which senders reach her attention first.

#### An automatic reply always has an end

**An automatic reply runs for a fixed period**

- **When** Mia asks her assistant to turn on her out-of-office reply from Monday to Friday with a short message
- **Then** Mia is asked to approve the reply first
- **And** after she approves, senders receive the message from Monday to Friday
- **But** no sender receives it on the Saturday after

**An automatic reply without an end date is refused**

- **When** Mia asks her assistant to turn on her out-of-office reply with no end date
- **Then** the assistant asks Mia for the last day of the reply
- **And** the reply stays off

**An automatic reply is turned off**

- **Given** Mia's out-of-office reply is on
- **When** Mia asks her assistant to turn it off
- **Then** senders receive no automatic reply

#### A sender has a fixed tab in the inbox

**Mail from one sender always lands in Focused**

- **Given** Mia receives mail from the CEO in the Other tab
- **When** Mia asks her assistant to always put mail from the CEO in Focused
- **Then** new mail from the CEO arrives in the Focused tab

## Files in OneDrive and SharePoint

### Finding and reading files in OneDrive and SharePoint

Mia and her colleagues keep documents in OneDrive and on SharePoint sites. Mia asks her assistant to find a document, to show what a folder holds, and to answer from the content of one file. The assistant sees only the files that Mia herself can open.

**Starting point.** Mia can open her own OneDrive, the Legal site, and the Sales site.

#### The assistant finds a file from what Mia remembers about it

**A file is found by a word in its name and by its type**

- **Given** the Legal site holds "Brightway Master Agreement.docx" and "Brightway Pricing.xlsx"
- **When** Mia asks her assistant for the Brightway agreement as a Word document
- **Then** the assistant shows "Brightway Master Agreement.docx"
- **But** it does not show "Brightway Pricing.xlsx"

**The file that was edited last comes first, with its editor**

- **Given** Mia has quarterly plans edited in January by Anna, in March by Tom, and in May by Priya
- **When** Mia asks her assistant for the quarterly plan that was edited last
- **Then** the assistant shows the May plan first
- **And** it names Priya as the editor

**A search stays on the site that Mia names**

- **Given** the Legal site and the Sales site each hold "NDA Template.docx"
- **When** Mia asks her assistant for the NDA template on the Legal site only
- **Then** the assistant shows the Legal copy
- **But** it does not show the Sales copy

**A missing file is reported as missing**

- **Given** no file that Mia can open mentions "Zephyr"
- **When** Mia asks her assistant for the Zephyr budget
- **Then** the assistant says that it found no matching file

#### The assistant shows what a folder holds, one level at a time

**A folder lists its files and subfolders, newest first**

- **Given** the folder "2026 Contracts" holds 12 files and 3 subfolders
- **When** Mia asks her assistant what "2026 Contracts" holds, newest first
- **Then** the assistant lists the 12 files and the 3 subfolders, newest first
- **But** it does not list what is inside the subfolders

#### The assistant answers from the content of one file

**The answer comes from the content of the file**

- **Given** Mia has a `<kind>` that states "the launch date is 14 June"
- **When** Mia asks her assistant for the launch date in that file
- **Then** the assistant answers "14 June"

| kind |
| --- |
| Word document |
| Excel workbook |
| PowerPoint deck |
| PDF |
| plain text file |

**A file that opens through a sharing link is read**

- **Given** Anna sent Mia a sharing link to the deck "Q3 Plan.pptx"
- **When** Mia asks her assistant to summarize what the sharing link opens
- **Then** the assistant summarizes "Q3 Plan.pptx"

**Several files of a folder answer one question**

- **Given** the folder "Tenders" holds 6 offers from 6 vendors
- **When** Mia asks her assistant which offer has the lowest price
- **Then** the assistant reads all 6 offers
- **And** it names the vendor with the lowest price

**A file of exactly 10 MB is read**

- **Given** Mia has a PDF of exactly 10 MB
- **When** Mia asks her assistant to summarize it
- **Then** the assistant summarizes the PDF

**A file above 10 MB is refused as a whole**

- **Given** Mia has a PDF of 10.5 MB
- **When** Mia asks her assistant to summarize it
- **Then** the assistant tells Mia that the file is too large to read
- **But** it does not summarize only a part of the file

**A file that Microsoft cannot provide is reported and not guessed**

- **Given** Microsoft cannot provide "Brightway Master Agreement.docx" as a PDF
- **When** Mia asks her assistant for that agreement as a PDF
- **Then** the assistant tells Mia that the file could not be read
- **But** it does not invent the content of the file

### Organizing and sharing files in OneDrive and SharePoint

Mia files documents and shares them with colleagues. Mia asks her assistant to create, move, copy, and delete files, and to give other people access. Each change asks for Mia's approval first. A delete moves an item to the recycle bin and erases nothing for good.

#### Mia files documents where she wants them

**Signed contracts move into a new folder**

- **Given** the folder "Contracts" holds 4 signed contracts
- **When** Mia asks her assistant to move them into a new folder "2026 Signed"
- **Then** Mia is asked to approve the change first
- **And** after she approves, "2026 Signed" holds the 4 contracts with their names

**A folder is copied to another drive**

- **Given** Mia has the folder "Template" of 20 files in her OneDrive
- **When** Mia asks her assistant to copy "Template" into the Sales site
- **Then** the Sales site holds a copy of "Template" with 20 files
- **And** "Template" stays in Mia's OneDrive

**A delete moves a file to the recycle bin**

- **Given** Mia has the file "Old draft.docx"
- **When** Mia asks her assistant to delete "Old draft.docx"
- **Then** "Old draft.docx" is in the recycle bin
- **But** it is not erased for good

**Meeting notes are saved as a new text file**

- **Given** Mia has the folder "Notes"
- **When** Mia asks her assistant to save these meeting notes as "Sync 14 June.txt" in "Notes"
- **Then** "Notes" holds "Sync 14 June.txt" with the notes

#### Mia gives access to a colleague and can take it back

**A colleague gets edit access**

- **Given** Mia has the file "Q3 Plan.pptx"
- **When** Mia asks her assistant to give Anna edit access to "Q3 Plan.pptx"
- **Then** Mia is asked to approve the access first
- **And** after she approves, Anna can edit "Q3 Plan.pptx"

**A sharing link is created and sent to nobody**

- **Given** Mia has the file "Q3 Plan.pptx"
- **When** Mia asks her assistant for a sharing link to "Q3 Plan.pptx"
- **Then** the assistant gives Mia the sharing link
- **But** nobody receives it from the assistant

#### Not supported yet

- The content of an existing file is replaced
- Access is taken back

## Microsoft Teams

### Catching up on Teams

Mia misses messages and meetings in Teams. Mia asks her assistant which conversations need her, where a topic was discussed, and what a meeting said. The assistant reads only the chats, channels, and meetings that Mia herself can see.

#### The assistant shows which conversations need Mia

**Chats with unread messages are listed with their last message**

- **Given** Mia has 9 chats, and the last message of 3 of them is unread
- **When** Mia asks her assistant which chats have unread messages
- **Then** the assistant lists those 3 chats
- **And** it shows the last message and the sender of each

**A chat without a title is shown by its members**

- **Given** Mia has a group chat with no title, and its members are Anna and Tom
- **When** Mia asks her assistant for her chats
- **Then** the assistant shows that chat as the chat with Anna and Tom

#### The assistant finds a message in any chat or channel

**A topic is found in a chat and in a channel**

- **Given** Tom wrote about the pricing change in a chat with Mia
- **And** Priya wrote about the pricing change in the channel "Sales"
- **When** Mia asks her assistant where the pricing change was discussed
- **Then** the assistant shows the message of Tom
- **And** it shows the message of Priya

**A channel is read with its replies**

- **Given** the channel "Releases" has 3 posts this week, and one post has 4 replies
- **When** Mia asks her assistant what happened in "Releases" this week
- **Then** the assistant gives the 3 posts
- **And** it includes the 4 replies under their post

#### The assistant tells Mia what a meeting said

**A transcript becomes a summary with action items**

- **Given** the "Design review" of yesterday has a transcript where Anna and Tom speak
- **When** Mia asks her assistant for a summary with the action items
- **Then** the summary says who said what
- **And** it lists the action items

**A transcript of three hours is read to its end**

- **Given** the transcript of a meeting runs for three hours and ends with a decision
- **When** Mia asks her assistant for the decisions of that meeting
- **Then** the assistant names the decision from the end of the transcript

**A meeting without a transcript is reported**

- **Given** nobody turned on the transcript in "Weekly sync"
- **When** Mia asks her assistant for a summary of "Weekly sync"
- **Then** the assistant tells Mia that no transcript exists

#### A recording is described and never handed over

**The assistant describes a recording and does not give it**

- **Given** "Design review" was recorded and runs for 52 minutes
- **When** Mia asks her assistant for the recording
- **Then** the assistant says that the recording exists and runs for 52 minutes
- **And** it says who may download it
- **But** it does not give the recording itself

### Posting in Teams

Mia lets her assistant write in Teams for her. Everyone in a chat or a channel sees what the assistant posts, so the assistant posts only after Mia approves it.

#### A message is posted after Mia approves it

**A chat message with a mention is posted**

- **Given** Mia has a chat with Anna and Tom
- **When** Mia asks her assistant to tell the chat that the build is green and to mention Anna
- **Then** Mia is asked to approve the message first
- **And** after she approves, the chat shows the message with a mention of Anna

**A declined message is not posted**

- **Given** Mia has a chat with Anna and Tom
- **When** Mia declines the message that her assistant proposed
- **Then** the chat shows no new message

**A person who is not in the chat is not mentioned**

- **Given** Priya is not a member of Mia's chat with Anna and Tom
- **When** Mia asks her assistant to post in that chat and to mention Priya
- **Then** the assistant tells Mia that Priya is not in the chat
- **And** nothing is posted

**A reply goes into the thread of a channel post**

- **Given** the channel "Releases" has a post "v2 is out?"
- **When** Mia asks her assistant to reply "Yes, since noon" to that post
- **Then** the reply is in the thread of "v2 is out?"
- **And** the channel shows no new top-level post

**A file that is in SharePoint is attached to a post**

- **Given** the deck "Q3 Plan.pptx" is in the Sales site
- **When** Mia asks her assistant to post "Q3 Plan.pptx" in the channel "Sales"
- **Then** the channel "Sales" shows a post with "Q3 Plan.pptx" attached

#### Mia changes only her own messages

**Mia's own message is corrected**

- **Given** Mia wrote "Launch on 14 Jun" in a chat
- **When** Mia asks her assistant to correct it to "Launch on 14 June"
- **Then** the chat shows "Launch on 14 June" in place of the old text

**A message of another person is not changed**

- **Given** Tom wrote "Launch on 14 Jun" in a chat
- **When** Mia asks her assistant to correct that message
- **Then** the assistant tells Mia that she can change only her own messages
- **And** the message of Tom is unchanged

### Running Teams chats and online meetings

Mia leads projects and starts group chats and online meetings for them. Mia asks her assistant to create a chat, to change who is in it, and to set up an online meeting. Everyone in a chat sees each change, so the assistant asks Mia to approve each one first.

#### Mia controls who is in a group chat

**A group chat is created and named**

- **When** Mia asks her assistant to start a group chat with Anna and Tom named "Launch"
- **Then** Mia is asked to approve the chat first
- **And** after she approves, the chat "Launch" has Mia, Anna, and Tom as members

**A new member sees the earlier messages only when Mia asks for it**

- **Given** the chat "Launch" holds 30 messages
- **When** Mia asks her assistant to add Priya to "Launch" with the earlier messages visible
- **Then** Priya sees the 30 earlier messages

**A member is removed from a group chat**

- **Given** the chat "Launch" has Anna, Tom, and Priya as members
- **When** Mia asks her assistant to remove Tom from "Launch"
- **Then** Mia is asked to approve the change first
- **And** after she approves, Tom is no longer a member of "Launch"

**A one-to-one chat keeps its two members**

- **Given** Mia has a one-to-one chat with Anna
- **When** Mia asks her assistant to add Tom to that chat
- **Then** the assistant tells Mia that a one-to-one chat takes no new member

#### An online meeting belongs to its organizer

**An online meeting is created with its attendees**

- **When** Mia asks her assistant to create an online meeting for tomorrow at 14:00 with Anna and Tom
- **Then** Mia receives the join address of the meeting
- **And** the meeting is on no calendar until someone adds it

**Attendance is shown only to the organizer**

- **Given** Anna organized "Design review" and Mia attended it
- **When** Mia asks her assistant who attended "Design review"
- **Then** the assistant tells Mia that only Anna can see the attendance

## Calendar

### Reading the calendar

Mia plans her day from her calendar. Mia asks her assistant what is on, who is coming, and when she next meets a person. The assistant reads Mia's own calendars and the calendars that others share with her.

**Starting point.** Mia works in Zurich.

#### The assistant shows a day or a week in Mia's time zone

**A day lists its meetings with their local times**

- **Given** Mia has meetings at 09:00 and at 15:00 tomorrow
- **When** Mia asks her assistant what is on her calendar tomorrow
- **Then** the assistant lists both meetings with their times in Zurich time

**A weekly meeting appears on its own date, also when one date moved**

- **Given** Mia's "Team sync" repeats every Thursday
- **And** Priya moved next week's "Team sync" to Friday at 10:00
- **When** Mia asks her assistant what is on her calendar next week
- **Then** the assistant shows "Team sync" on Friday at 10:00
- **But** it does not show "Team sync" on Thursday

**Overlapping meetings are named as a clash**

- **Given** Mia has a meeting from 14:00 to 15:00 and another from 14:30 to 15:30 tomorrow
- **When** Mia asks her assistant whether she has a clash tomorrow
- **Then** the assistant names both meetings as a clash

#### The assistant tells Mia who is coming

**The attendees of a meeting are shown with their answers**

- **Given** Mia's "Launch review" has Anna who accepted, Tom who declined, and Priya who did not answer
- **When** Mia asks her assistant who is coming to "Launch review"
- **Then** the assistant says that Anna accepted
- **And** it says that Tom declined
- **And** it says that Priya did not answer

#### A meeting is reached from the mail that invites to it

**The meeting behind an invitation mail is opened**

- **Given** Anna invited Mia to "Launch review" by mail
- **When** Mia asks her assistant for the details of the meeting in Anna's mail
- **Then** the assistant shows the time of "Launch review"
- **And** it shows who else is invited

#### A meeting that no longer exists is reported and not invented

**A deleted meeting is reported as gone**

- **Given** Mia's assistant listed "Budget review" and Anna then deleted it
- **When** Mia asks her assistant for the details of "Budget review"
- **Then** the assistant tells Mia that the meeting no longer exists

#### Not supported yet

- The next meeting with a given person is found

### Scheduling and answering meetings

Mia sets up meetings and answers the invitations that she receives. Mia asks her assistant to find a time that suits everyone, to book it, to move it, and to answer an invitation. A meeting that invites other people goes out only after Mia approves it.

#### Mia answers an invitation in her own words

**An invitation is accepted**

- **Given** Anna invited Mia to "Launch review"
- **When** Mia asks her assistant to accept "Launch review"
- **Then** Anna sees Mia as accepted

**An invitation is declined with a note**

- **Given** Anna invited Mia to "Launch review" on Friday
- **When** Mia asks her assistant to decline it with the note "I am on leave"
- **Then** Anna sees Mia as declined
- **And** Anna sees the note "I am on leave"

**A new time is proposed only when the organizer allows it**

- **Given** Anna does not allow new time proposals for "Launch review"
- **When** Mia asks her assistant to decline it and propose Monday at 10:00
- **Then** the assistant tells Mia that Anna allows no new time
- **And** Anna sees no proposal

#### Mia finds a time before she books

**A time is suggested when all attendees are free**

- **Given** Anna and Tom are busy on Monday morning and free in the afternoon
- **And** Mia is free all day Monday
- **When** Mia asks her assistant for 30 minutes with Anna and Tom on Monday
- **Then** the assistant suggests times in the afternoon
- **But** it suggests no time in the morning

#### A meeting is booked after Mia approves it

**A meeting with an online Teams meeting is booked and invitations go out**

- **Given** Mia agreed on Monday at 14:00 with Anna and Tom
- **When** Mia asks her assistant to book "Launch review" with Teams
- **Then** Mia is asked to approve the meeting first
- **And** after she approves, "Launch review" is on Mia's calendar with a Teams meeting
- **And** Anna and Tom each receive an invitation

**A weekly meeting is booked as one series**

- **When** Mia asks her assistant to book "Stand-up" every Monday for 8 weeks
- **Then** Mia's calendar holds 8 occurrences of "Stand-up"
- **And** the 8 occurrences belong to one series

**A meeting room is booked with the meeting**

- **Given** the room "Maple" seats 8 and is free on Monday at 14:00
- **When** Mia asks her assistant to book "Workshop" with 6 people in a room
- **Then** the room "Maple" is invited to "Workshop"

#### Only the organizer changes or cancels a meeting

**One date of a series moves and the other dates stay**

- **Given** Mia organizes the weekly "Team sync" on Thursday
- **When** Mia asks her assistant to move next Thursday's "Team sync" to Friday
- **Then** only the occurrence of next Thursday moves to Friday
- **But** the other occurrences stay on Thursday

**A whole series is cancelled and attendees are told**

- **Given** Mia organizes the weekly "Team sync" with Anna and Tom
- **When** Mia asks her assistant to cancel the whole series
- **Then** no occurrence of "Team sync" stays on Mia's calendar
- **And** Anna and Tom each receive a cancellation

**A meeting of another organizer is not changed**

- **Given** Anna organizes "Launch review"
- **When** Mia asks her assistant to move "Launch review" to Friday
- **Then** the assistant tells Mia that only Anna can change "Launch review"
- **And** "Launch review" stays on its time

#### Not supported yet

- An invitation is drafted for Mia to review before it goes out
- A meeting is booked on a calendar other than the main one

### Sharing and delegating calendars

Mia works with an executive assistant, Priya, and she shares calendars with her team. Mia asks her assistant to share a calendar, to act on a calendar that someone delegated to her, and to read a team calendar.

#### Mia shares her own calendar and can stop sharing it

**A colleague is given read access to a calendar**

- **When** Mia asks her assistant to let Anna see her calendar
- **Then** Mia is asked to approve the share first
- **And** after she approves, Anna can see Mia's calendar once she accepts the invitation

**A share is stopped**

- **Given** Anna can see Mia's calendar
- **When** Mia asks her assistant to stop sharing her calendar with Anna
- **Then** Mia is asked to approve the change first
- **And** after she approves, Anna can no longer see Mia's calendar

#### A delegate acts in the name of the person who delegated

**A meeting is booked on the calendar of a manager**

- **Given** Mia's manager Lena delegated her calendar to Mia
- **When** Mia asks her assistant to book "Budget review" on Lena's calendar
- **Then** "Budget review" is on Lena's calendar
- **And** the invitations to the attendees name Lena as the sender

**A calendar without delegation is not changed**

- **Given** Lena did not delegate her calendar to Mia
- **When** Mia asks her assistant to book "Budget review" on Lena's calendar
- **Then** the assistant tells Mia that she has no access to Lena's calendar
- **And** Lena's calendar is unchanged

#### A team calendar shows the events of the whole team

**The events of a team calendar are listed for a week**

- **Given** the team "Platform" has 4 events on its calendar this week
- **When** Mia asks her assistant what is on the calendar of "Platform" this week
- **Then** the assistant lists the 4 events

## Notes in OneNote

### Working with notes in OneNote

Mia keeps her notes in OneNote notebooks, and her team keeps shared notebooks. Mia asks her assistant to find a note, to read it, to capture new notes, and to change a note. A change in a notebook of a team or a site needs Mia's approval first.

#### The assistant finds a note by its title and not by its content

**A page is found by a word in its title**

- **Given** Mia has the page "Acme kickoff" in the notebook "Customers"
- **When** Mia asks her assistant for her notes from the Acme kickoff
- **Then** the assistant shows the page "Acme kickoff"

**A notebook is opened from a web address**

- **Given** Anna sent Mia the web address of the notebook "Customers"
- **When** Mia asks her assistant for the sections of that notebook
- **Then** the assistant lists the sections of "Customers"

#### The assistant captures and changes notes

**New notes become a page in a section**

- **Given** Mia has the section "Work" in her notebook "Customers"
- **When** Mia asks her assistant to create the page "Weekly sync" with three notes in "Work"
- **Then** the section "Work" holds the page "Weekly sync"
- **And** the page holds the three notes in order

**A task list is added to the end of an existing page**

- **Given** Mia has the page "Planning" with 2 paragraphs
- **When** Mia asks her assistant to add a task list at the end of "Planning"
- **Then** "Planning" ends with the task list
- **But** its 2 paragraphs are unchanged

**A sentence is changed in place**

- **Given** the page "Planning" states "Launch on 14 June" in its second paragraph
- **When** Mia asks her assistant to change that date to 21 June
- **Then** the second paragraph states "Launch on 21 June"
- **But** the other paragraphs are unchanged

**A page is erased only after Mia approves**

- **Given** Mia has the page "Old draft"
- **When** Mia asks her assistant to erase "Old draft"
- **Then** Mia is asked to approve the erase first
- **And** the assistant tells Mia that OneNote keeps no copy of an erased page

#### A change in a team notebook needs Mia's approval

**A page is added to the notebook of a team**

- **Given** Mia belongs to the team "Platform", which owns a notebook
- **When** Mia asks her assistant to add the page "Retro" to the notebook of "Platform"
- **Then** Mia is asked to approve the change first
- **And** after she approves, the notebook of "Platform" holds "Retro"

#### Not supported yet

- A page is found by a word that is only in its body

## Contacts

### Managing contacts

Mia keeps the people she works with in her Outlook contacts. Mia asks her assistant to look up a person, to save a new contact, and to add a detail to a contact.

#### The assistant answers from Mia's contacts

**A phone number is found in a contact**

- **Given** Mia has the contact Anna Meier with the telephone number "+41 44 555 01 01"
- **When** Mia asks her assistant for the telephone number of Anna Meier
- **Then** the assistant answers "+41 44 555 01 01"

#### A change to a contact keeps what it already holds

**A new contact is saved**

- **When** Mia asks her assistant to save Tom Berger of Acme with the address "tom@acme.example" as a contact
- **Then** Mia's contacts hold one contact Tom Berger with the company "Acme" and that address

**A second telephone number is added next to the first**

- **Given** Mia has the contact Tom Berger with the mobile number "+41 79 555 01 02"
- **When** Mia asks her assistant to add the office number "+41 44 555 01 03" to Tom Berger
- **Then** the contact Tom Berger holds both numbers

#### Not supported yet

- A person who is only in the company directory is found

## Across mail, calendar, and files

### Working across mail, calendar, and files

Mia's work does not stay in one application. A message leads to a meeting, and a meeting leads to a document. Mia asks her assistant for one answer that needs more than one source. The assistant uses only what Mia herself can see in her mailbox, her calendar, and her files.

#### Mia starts her day with one overview

**A morning brief joins meetings and mail**

- **Given** Mia has 3 meetings today and 12 unread messages, 2 of them from her manager
- **When** Mia asks her assistant for a brief of her day
- **Then** the assistant lists the 3 meetings with their attendees
- **And** it names the 2 messages of her manager first among the unread mail

#### Mia goes through her inbox in one sitting

**A meeting invitation is not answered without Mia**

- **Given** Mia's inbox holds 9 newsletters and one meeting invitation from Anna
- **When** Mia asks her assistant to go through her inbox
- **Then** the assistant files the 9 newsletters in "Newsletters"
- **But** it asks Mia how to answer the invitation of Anna

**A reply uses a document from SharePoint**

- **Given** Anna asked Mia by mail for the latest price list
- **And** the latest price list is in the Sales site
- **When** Mia asks her assistant to answer Anna with the latest price list
- **Then** the draft to Anna quotes the prices of the latest price list
- **And** the draft is not sent

**A thread leads to a time for a workshop**

- **Given** Anna and Tom discussed a workshop in a thread of 8 messages
- **And** they need a time next week
- **When** Mia asks her assistant to find a time for the workshop that the thread describes
- **Then** the assistant names times next week when Mia, Anna, and Tom are free

<!-- use-cases:end -->
