# office-365-mcp use cases

!!! danger "Documentation Disclaimer"
    This feature is `EXPERIMENTAL` and under active development. It may change significantly, be
    discontinued, or have breaking changes without notice.

## Overview

This page shows what people ask an assistant to do when office-365-mcp connects it to Microsoft 365.
The examples follow Mia. Mia works with an assistant that reaches her mail, her calendar, her files,
Microsoft Teams, and her notes.

Each example has the same parts. "Ask your assistant" shows a prompt that Mia can type. "Situation"
shows a starting point. "What happens" shows what the assistant does. "Limit" shows a part that does
not work as Mia expects. A part named "Not supported yet" lists what people ask for and what the
server cannot do today.

The examples come from how people use the server and from what its tools can do. Not every example
was run by hand. For the tools behind the examples, read the [tool reference](README.md).

## Rules for every example

- The assistant sees only what Mia can see in Microsoft 365.
- The assistant asks Mia to approve each change that other people can see, such as a message, an
  invitation, or a share.
- The assistant sends no mail before Mia approves the draft.
- The assistant erases no mail and no file for good. A delete moves the item to Deleted Items or to
  the recycle bin. OneNote has no recycle bin, so the assistant asks Mia before it erases a page.

<!-- use-cases:begin -->

**On this page**

- Outlook: [Finding and reading mail](#finding-and-reading-mail), [Drafting and sending mail](#drafting-and-sending-mail), [Organizing the mailbox](#organizing-the-mailbox), [Mailbox preferences](#mailbox-preferences), [Reading the calendar](#reading-the-calendar), [Scheduling and answering meetings](#scheduling-and-answering-meetings), [Sharing and delegating calendars](#sharing-and-delegating-calendars), [Managing contacts](#managing-contacts)
- Teams: [Catching up on Teams](#catching-up-on-teams), [Posting in Teams](#posting-in-teams), [Running Teams chats and online meetings](#running-teams-chats-and-online-meetings)
- SharePoint: [Finding and reading files in OneDrive and SharePoint](#finding-and-reading-files-in-onedrive-and-sharepoint), [Organizing and sharing files in OneDrive and SharePoint](#organizing-and-sharing-files-in-onedrive-and-sharepoint)
- OneNote: [Working with notes in OneNote](#working-with-notes-in-onenote)
- Across sources: [Working across mail, calendar, files, and Teams](#working-across-mail-calendar-files-and-teams)

## Outlook

### Finding and reading mail

Mia receives far more mail than she can read. Mia asks her assistant to find messages, to read one in full with its attachments, and to follow a whole conversation. The assistant reads Mia's own mailbox, and a shared mailbox when Mia has access to it.

#### The assistant finds a message from what Mia remembers about it

**Unread mail since yesterday is listed**

Ask your assistant: "Which of my messages since yesterday are unread?"

Situation: Mia received 6 messages since yesterday morning, and 2 of them are unread.

What happens:

- The assistant lists the 2 unread messages.
- It does not list the 4 messages that Mia read.

**A message is found by sender, subject, and attachment together**

Ask your assistant: "Find the March invoice from Brightway that has a PDF."

Situation: Brightway sent "March invoice" with a PDF, and sent "March invoice reminder" with no attachment.

What happens:

- The assistant shows "March invoice".
- It does not show "March invoice reminder".

**A time window narrows the result**

Ask your assistant: "Show me the messages that Anna sent me in March."

Situation: Anna sent Mia one message in February, one in March, and one in April.

What happens:

- The assistant shows only the March message.

**Flagged mail is listed**

Ask your assistant: "Which of my messages are flagged?"

Situation: Mia flagged 2 messages for follow-up and did not flag 5 others.

What happens:

- The assistant lists the 2 flagged messages.

**A result that may be incomplete says so**

Ask your assistant: "Show me every message that mentions invoice."

Situation: 1,500 messages mention "invoice", which is more than one search returns.

What happens:

- The assistant shows the messages that the search returns.
- It tells Mia that more matching messages may exist.

**Mail that Mia sent to one person about a topic is found**

Ask your assistant: "What did I send to Tom about the offer?"

Situation: Mia sent Tom "Offer for Brightway" and sent Anna "Offer draft". Tom sent Mia "Offer questions".

What happens:

- The assistant shows "Offer for Brightway".
- It does not show "Offer draft" or "Offer questions".

**The number of unread messages is given with the newest ones**

Ask your assistant: "How many of my messages are unread, and which 5 are the newest?"

Situation: Mia's inbox holds 120 unread messages.

What happens:

- The assistant tells Mia that 120 messages are unread.
- It lists the 5 newest unread messages.

**The latest message from one person is shown**

Ask your assistant: "Show me the last message from Anna."

Situation: Anna sent Mia a message on Monday, one on Tuesday, and one on Wednesday.

What happens:

- The assistant shows the message of Wednesday.
- It does not show the messages of Monday and Tuesday.

**Mail that went to Junk is found**

Ask your assistant: "Did the invoice from Brightway go to junk?"

Situation: Brightway sent "March invoice", which landed in Mia's Junk Email folder, and Mia's inbox holds 20 other messages.

What happens:

- The assistant shows "March invoice" and says that it is in Junk Email.
- It does not list messages of Mia's inbox.

#### The assistant reads a message and its attachments

**A message is read in full and its attachments are named**

Ask your assistant: "Read the Contract draft message to me and tell me what is attached."

Situation: Anna sent "Contract draft" with the attachment "Draft v2.docx" of 80 KB.

What happens:

- The assistant gives the full text of the message.
- It names "Draft v2.docx" with its size.

**The content of an Excel attachment answers a question**

Ask your assistant: "What is the total in the last row of the Excel file that Anna attached?"

!!! warning "Limit"
    The assistant may not be able to read the numbers inside an Excel attachment.

Situation: Anna attached a 2 MB Excel workbook with a total of 4,200 in its last row.

What happens:

- The assistant answers 4,200.

**An attachment above 10 MB is refused**

Ask your assistant: "Read the PDF that Anna attached to her message."

Situation: Anna attached a 12 MB PDF.

What happens:

- The assistant tells Mia that the attachment is too large to read.
- It tells Mia to open the message in Outlook.

**The content of a PDF attachment answers a question**

Ask your assistant: "What is the amount due on the invoice that Brightway sent as a PDF?"

Situation: Brightway sent "March invoice" with a 1 MB PDF that gives an amount due of 3,150.

What happens:

- The assistant answers 3,150.

#### The assistant follows a conversation from first message to last

**A decision is found in a long conversation**

Ask your assistant: "What did we decide in the conversation about the launch?"

Situation: A conversation of 5 messages between Mia, Anna, and Tom ends with a long message that gives a decision to launch on 14 June near its end.

What happens:

- The assistant answers that the launch is on 14 June.

#### A shared mailbox is read only with Mia's access

**Unread mail of a shared mailbox is listed**

Ask your assistant: "Show me the unread messages in support@example.com."

Situation: Mia has access to the shared mailbox "support@example.com", which holds 3 unread messages.

What happens:

- The assistant lists the 3 unread messages of "support@example.com".
- It does not list messages of Mia's own mailbox.

#### Not supported yet in finding and reading mail

- The assistant says that an administrator must grant the connector a permission, and not that Mia has no access to the mailbox.

### Drafting and sending mail

Mia lets her assistant write mail for her. The assistant leaves each message as a draft for Mia to read, and sends it only after Mia approves.

#### A draft goes to the real address of the right person

**A draft is addressed to the address of the named person**

Ask your assistant: "Draft a note to Anna Meier that asks for the contract by Friday."

Situation: Anna Meier works in Legal and has the address "anna.meier@example.com".

What happens:

- The draft is addressed to "anna.meier@example.com".
- The draft asks for the contract by Friday.

**Two people with one name lead to a question**

Ask your assistant: "Write a note to Anna Meier."

Situation: Anna Meier in Legal has the address "anna.meier@example.com". Anna Meier in Sales has the address "anna.meier.sales@example.com".

What happens:

- The assistant asks Mia which Anna Meier she means.
- It does not create the draft yet.

**A name that matches no one closely leads to a question**

Ask your assistant: "Write a note to Anna Mayer."

Situation: Anna Meier works in Legal and has the address "anna.meier@example.com". Nobody in the directory is named "Anna Mayer".

What happens:

- The assistant asks Mia whether she means Anna Meier.
- It does not create the draft yet.

**Mia asks whether Anna is away**

Ask your assistant: "Is Anna away right now?"

Situation: Anna works in Mia's organization and has an automatic reply turned on.

What happens:

- The assistant tells Mia the text of the automatic reply of Anna.

#### A draft changes until Mia approves it

**A draft is shortened in place**

Ask your assistant: "Make the draft shorter."

Situation: Mia has a draft to Anna with 4 paragraphs.

What happens:

- The same draft has fewer words.
- The shorter text still names the same facts.
- Mia's mailbox holds no second draft.

**A person is not both addressed and copied**

Ask your assistant: "Copy Tom on the draft as well."

Situation: Mia has a draft addressed to Tom.

What happens:

- The assistant tells Mia that Tom is already on the draft.
- The draft stays as it is until Mia chooses.

**The subject, the importance, and a recipient of a draft change**

Ask your assistant: "Take Priya off my draft, call it Contract for signature, and mark it important."

Situation: Mia has a draft with the subject "Contract" addressed to Anna and Priya.

What happens:

- The same draft is addressed to Anna only.
- Its subject is "Contract for signature".
- It is marked important.
- Mia's mailbox holds no second draft.

#### Nothing is sent without Mia's approval

**An approved draft is sent**

Ask your assistant: "Send the draft to Anna."

Situation: Mia read her draft to Anna.

What happens:

- The message is in Mia's sent items.
- Anna receives it once.
- The assistant asks Mia to approve first.

**A declined draft stays a draft**

Ask your assistant: "Send the contract draft to Anna."

Situation: Mia has a draft about the contract addressed to Anna.

What happens:

- Mia is asked to approve the send, and she declines.
- Anna receives nothing.
- The draft is still in Mia's drafts.

**A draft that changed after the question is not sent**

Ask your assistant: "Send my draft to Anna."

Situation: Mia was asked to approve a draft to Anna. The text of the draft changed after that question.

What happens:

- Anna receives nothing.
- The assistant tells Mia that the draft changed.
- Mia is asked to approve the draft as it is now.

**Mia is warned about an automatic reply before a send**

Ask your assistant: "Send Anna the draft now."

Situation: Mia has a draft addressed to Anna. Anna works in Mia's organization and has an automatic reply turned on.

What happens:

- The assistant tells Mia about the automatic reply of Anna.
- Mia is asked to approve that the draft is sent.

**A send that Mia cannot approve sends nothing**

Ask your assistant: "Please send my draft to Anna."

Situation: Mia has a draft addressed to Anna. Mia's chat program cannot show her a question.

What happens:

- Anna receives nothing.
- The assistant tells Mia that her program cannot ask her.
- The draft is still in Mia's drafts.

**A draft that Mia wrote in Outlook is sent**

Ask your assistant: "Send the draft I just wrote to Tom."

Situation: Mia wrote a draft to Tom in Outlook and left it in her drafts.

What happens:

- Mia is asked to approve that the draft is sent.
- After she approves, Tom receives it.

Other people use a shared mailbox, so the assistant changes it only after Mia approves.

**A draft in a shared mailbox needs Mia's approval**

Ask your assistant: "Draft a note to customer@acme.example from the support mailbox that confirms the order."

Situation: Mia has access to the shared mailbox "support@example.com".

What happens:

- Mia is asked to approve the draft first.
- After she approves, the draft is in the drafts of "support@example.com".

#### A reply keeps the conversation

**A reply to everyone lists every other person**

Ask your assistant: "Reply to everyone on Anna's message."

Situation: Anna wrote to Mia, Tom, and Priya.

What happens:

- The draft is addressed to Anna, Tom, and Priya.
- It is not addressed to Mia.

**A plain reply goes to the sender only**

Ask your assistant: "Reply to Anna's message and say Friday works."

Situation: Anna wrote to Mia and Tom.

What happens:

- The draft is addressed to Anna.
- It is not addressed to Tom.

**A forward carries the original attachments**

Ask your assistant: "Forward the mail Contract draft to Tom with a short note."

Situation: Anna sent Mia "Contract draft" with the attachment "Draft v2.docx".

What happens:

- The draft to Tom holds "Draft v2.docx".

#### Not supported yet in drafting and sending mail

- The assistant cannot add a blind copy to a draft yet.
- The assistant cannot attach a file to a draft yet.

### Organizing the mailbox

Mia keeps her mailbox in order with folders, categories, and inbox rules. Mia asks her assistant to file, mark, and sort mail in bulk, and to set up rules that do it for her later. The assistant erases no mail for good. A delete moves mail to Deleted Items.

#### A batch is checked whole and reported for each message

**A batch is filed in one folder**

Ask your assistant: "File the 8 newsletters from last month in my Newsletters folder."

Situation: Mia has 8 newsletters from last month in her inbox.

What happens:

- All 8 newsletters are in "Newsletters".
- Her inbox holds none of them.

**A batch is marked in one step**

Ask your assistant: "Mark all 8 newsletters from last month as read."

Cases:

- Mia has 8 newsletters from last month in her inbox. All 8 newsletters are marked as read.
- Mia has 8 newsletters from last month in her inbox. All 8 newsletters are flagged for follow-up.
- Mia has 8 newsletters from last month in her inbox. All 8 newsletters carry the category "Reading".

**A flag carries a due date**

Ask your assistant: "Flag the 3 messages from Tom for follow-up by Friday."

Situation: Mia has 3 messages from Tom in her inbox.

What happens:

- The 3 messages are flagged for follow-up.
- Each flag is due on Friday.

**Messages that Mia names by subject are found again and filed**

Ask your assistant: "File these 5 messages in my Archive folder."

!!! warning "Limit"
    The assistant sometimes cannot move mail at first, because it names a message in the wrong way. It then searches again and moves the messages.

Situation: Mia named 5 messages by their subjects only.

What happens:

- The assistant finds the 5 messages in her mailbox.
- All 5 messages are in "Archive".

**A batch with one missing message moves the others**

Ask your assistant: "File these 5 messages in my Archive folder."

Situation: Mia asks her assistant to file 5 messages in "Archive". One of the 5 messages is gone from her mailbox.

What happens:

- 4 messages are in "Archive".
- The assistant tells Mia which message failed.

**A delete moves mail to Deleted Items**

Ask your assistant: "Delete the 3 old messages from the vendor."

Situation: Mia has 3 old messages from a vendor.

What happens:

- The 3 messages are in Deleted Items.
- None of them is erased for good.

**A batch is archived**

Ask your assistant: "Archive the 6 messages from last month in my inbox."

Situation: Mia has 6 messages from last month in her inbox.

What happens:

- All 6 messages are in her archive.
- Her inbox holds none of them.

**A message is kept in a second folder**

Ask your assistant: "Keep a copy of the message Signed contract in my Contracts folder."

Situation: Mia has the message "Signed contract" in her inbox.

What happens:

- The folder "Contracts" holds a copy of "Signed contract".
- The original is still in her inbox.

**A change in a shared mailbox needs Mia's approval**

Ask your assistant: "File the message Refund question of the support mailbox in its Handled folder."

Situation: Mia has access to the shared mailbox "support@example.com". That mailbox holds the message "Refund question".

What happens:

- Mia is asked to approve the change first.
- The message stays where it is until she approves.

#### Mia keeps her folders as she names them

**A folder is created inside another folder**

Ask your assistant: "Create a folder Alpha inside Projects."

Situation: Mia has the folder "Projects".

What happens:

- "Projects" holds the folder "Alpha".

**A folder is renamed and keeps its mail**

Ask your assistant: "Rename the folder Old to Archive 2025."

Situation: The folder "Old" holds 40 messages.

What happens:

- The folder "Archive 2025" holds the 40 messages.

**A folder moves to Deleted Items only after Mia approves**

Ask your assistant: "Delete the folder Temp."

Situation: The folder "Temp" holds 5 messages and a subfolder.

What happens:

- Mia is asked to approve the delete first.
- After she approves, "Temp" with all of its content is in Deleted Items.

**A built-in folder is never renamed or deleted**

Ask your assistant: "Delete my Inbox folder."

What happens:

- The assistant tells Mia that Outlook keeps "Inbox" for every mailbox.
- The folder "Inbox" is unchanged.

**Two folders with one name lead to a question**

Ask your assistant: "File these 3 invoices in my Finance folder."

Situation: Mia has a folder "Finance" inside her inbox. Mia has a folder "Finance" inside her archive.

What happens:

- The assistant asks Mia which folder "Finance" she means.
- No invoice is moved yet.

#### Deleted mail stays in Deleted Items

The assistant cannot erase mail for good, so Mia empties Deleted Items herself.

**Deleted Items is emptied only by Mia**

Ask your assistant: "Empty my Deleted Items."

Situation: Deleted Items holds 120 messages.

What happens:

- The assistant tells Mia to empty Deleted Items in Outlook.
- Deleted Items still holds the 120 messages.

#### A category names a kind of mail across all folders

**A new category is created and put on mail**

Ask your assistant: "Create a red category Follow-up Q4 and put it on my unread messages from Tom Berger."

!!! warning "Limit"
    The assistant creates the category and puts it on mail only when the administrator has turned on both groups of tools.

Situation: Mia has 4 unread messages from Tom Berger.

What happens:

- The category "Follow-up Q4" exists and is red.
- The 4 messages carry it.

**A category is renamed**

Ask your assistant: "Rename my category Follow-up Q4 to Follow-up Q1."

!!! warning "Limit"
    The assistant cannot rename a category. It makes a new category with the new name and moves the 4 messages to it. The old category stays in the list.

Situation: Mia has the category "Follow-up Q4" on 4 messages.

What happens:

- Mia's categories hold "Follow-up Q1".
- The 4 messages carry "Follow-up Q1".

#### An inbox rule acts on new mail without Mia

**A rule files mail from one sender**

Ask your assistant: "Make a rule that moves mail from billing@example.com to my Finance folder."

!!! warning "Limit"
    The assistant cannot find the folder for a rule unless the administrator turns on the folder tools next to the rule tools.

What happens:

- Mia's rules include a rule with that sender and that folder.
- New mail from "billing@example.com" arrives in "Finance".

**An old rule is turned off and stays in the list**

Ask your assistant: "Turn off my Receipts rule."

Situation: Mia has the rule "Receipts".

What happens:

- "Receipts" is still in Mia's rules.
- It no longer acts on new mail.

**A rule that forwards mail needs approval that names every address**

Ask your assistant: "Make a rule that forwards mail from ceo@example.com to anna@example.com and tom@example.com."

What happens:

- Mia is asked to approve the rule first.
- The question names "anna@example.com" and "tom@example.com".

**A rule is erased only after Mia approves**

Ask your assistant: "Delete my Receipts rule."

Situation: Mia has the rule "Receipts".

What happens:

- Mia is asked to approve the erase first.
- After she approves, "Receipts" is no longer in her rules.

**A rule never erases mail for good**

Ask your assistant: "Make a rule that deletes mail from spam@example.com."

What happens:

- New mail from "spam@example.com" arrives in Deleted Items.
- None of it is erased for good.

**A rule without a clear condition is checked with Mia first**

Ask your assistant: "Make a rule that moves the mail I do not need to my Archive folder."

!!! warning "Limit"
    The assistant may create a rule for every new message without asking which mail Mia means.

What happens:

- The assistant asks Mia which mail the rule is for.
- The assistant tells Mia that a rule without a condition acts on every new message.
- No rule exists until Mia names the mail or agrees.

**A rule is narrowed**

Ask your assistant: "Change my rule Billing to Finance so that it moves only mail with invoice in the subject."

Situation: Mia has the rule "Billing to Finance" that moves mail from "billing@example.com".

What happens:

- The rule "Billing to Finance" needs both the sender and the word "invoice".
- Mia's rules hold no second rule with that name.

**A rule that is off is turned on again**

Ask your assistant: "Turn my Receipts rule on again."

Situation: Mia has the rule "Receipts" turned off.

What happens:

- "Receipts" acts on new mail again.
- Mia's rules hold no second rule named "Receipts".

### Mailbox preferences

Mia sets how her mailbox behaves while she is away and which senders reach her attention first.

#### An automatic reply always has an end

**An automatic reply runs for a fixed period**

Ask your assistant: "Turn on my out-of-office reply from Monday to Friday and tell everyone I am away."

!!! warning "Limit"
    The assistant can leave outside senders without a reply. It can also stop the reply a day early or use the wrong time zone.

What happens:

- The stored reply is scheduled from Monday 00:00 to Saturday 00:00 in Mia's time zone.
- The stored reply holds the message for senders inside and outside the organization.
- The assistant asks Mia to approve first.

**An automatic reply without an end date is refused**

Ask your assistant: "Turn on my out-of-office reply until I say otherwise."

What happens:

- The assistant asks Mia for the last day of the reply.
- The reply stays off.

**An automatic reply is turned off**

Ask your assistant: "Turn off my out-of-office reply."

Situation: Mia's out-of-office reply is on.

What happens:

- Senders receive no automatic reply.

#### Mia can see the state of her automatic reply

**The state of the automatic reply is read**

Ask your assistant: "Is my out-of-office reply on?"

Situation: Mia's out-of-office reply is on until Friday with the message "I am away until Monday".

What happens:

- The assistant tells Mia that the reply is on until Friday.
- It gives the message "I am away until Monday".

#### An automatic reply starts only after Mia agrees

The reply answers every sender, and nobody can recall an answer that went out.

**An automatic reply starts only after Mia approves it**

Ask your assistant: "Turn on my out-of-office reply from Monday to Friday."

What happens:

- Mia is asked to approve the reply first.
- Her out-of-office reply stays off until she approves.

**A declined automatic reply stays off**

Ask your assistant: "Turn on my out-of-office reply from Monday to Friday."

Situation: Mia's out-of-office reply is off.

What happens:

- The assistant tells Mia that the reply was not turned on.
- Senders receive no automatic reply.
- The assistant asks Mia to approve first.

#### A sender has a fixed tab in the inbox

**Mail from one sender always lands in Focused**

Ask your assistant: "Always put mail from ada@acme.example in my Focused tab."

Situation: Mia receives mail from Ada Keller at "ada@acme.example" in the Other tab.

What happens:

- The list of fixed senders holds "ada@acme.example" in the Focused tab.

### Reading the calendar

Mia plans her day from her calendar. Mia asks her assistant what is on, who is coming, and when she next meets a person. The assistant reads Mia's own calendars and the calendars that others share with her.

**Starting point.** Mia works in Zurich.

#### The assistant shows a day or a week in Mia's time zone

**A day lists its meetings with their local times**

Ask your assistant: "What is on my calendar tomorrow?"

Situation: Mia has meetings at 09:00 and at 15:00 tomorrow.

What happens:

- The assistant lists both meetings with their times in Zurich time.

**A weekly meeting appears on its own date, also when one date moved**

Ask your assistant: "What do I have on my calendar next week?"

Situation: Mia's "Team sync" repeats every Thursday. Priya moved next week's "Team sync" to Friday at 10:00.

What happens:

- The assistant shows "Team sync" on Friday at 10:00.
- It does not show "Team sync" on Thursday.

**Overlapping meetings are named as a clash**

Ask your assistant: "Do I have a clash in my calendar tomorrow?"

Situation: Mia has a meeting from 14:00 to 15:00 and another from 14:30 to 15:30 tomorrow.

What happens:

- The assistant names both meetings as a clash.

#### The assistant tells Mia who is coming

**The attendees of a meeting are shown with their answers**

Ask your assistant: "Who is coming to the Launch review, and who has answered?"

Situation: Mia organizes "Launch review" and it has Anna who accepted, Tom who declined, and Priya who did not answer.

What happens:

- The assistant says that Anna accepted.
- It says that Tom declined.
- It says that Priya did not answer.

**The next meeting with a given person is found**

Ask your assistant: "When is my next meeting with Tom?"

Situation: Mia has a meeting with Tom on Friday and another on the Tuesday after.

What happens:

- The assistant names the meeting on Friday.

#### A meeting is reached from the mail that invites to it

**The meeting behind an invitation mail is opened**

Ask your assistant: "What are the details of the meeting in Anna's invitation mail?"

Situation: Anna invited Mia to "Launch review" by mail.

What happens:

- The assistant shows the time of "Launch review".
- It shows who else is invited.

#### A meeting that cannot be read is reported and not invented

**A meeting that cannot be read is reported as unread**

Ask your assistant: "Give me the details of the Budget review."

Situation: Mia's assistant listed "Budget review" and Anna then deleted it.

What happens:

- The assistant tells Mia that it could not read "Budget review".
- It does not say that the meeting was deleted.

#### The assistant reads a calendar that a colleague shared with Mia

**The shared calendar of a colleague is read**

Ask your assistant: "What is on Anna's calendar tomorrow?"

Situation: Anna shared her calendar with Mia. Anna has "Design review" tomorrow at 11:00.

What happens:

- The assistant lists "Design review" at 11:00 in Zurich time.

#### The assistant reads the files that are attached to a meeting

**The agenda that is attached to an invitation is read**

Ask your assistant: "What is in the agenda that is attached to the Launch review?"

Situation: Anna's invitation "Launch review" holds the attached file "agenda.pdf".

What happens:

- The assistant names "agenda.pdf" as the attachment of "Launch review".
- It tells Mia the first topic of the agenda.

### Scheduling and answering meetings

Mia sets up meetings and answers the invitations that she receives. Mia asks her assistant to find a time that suits everyone, to book it, to move it, and to answer an invitation. A meeting that invites other people goes out only after Mia approves it.

#### Mia answers an invitation in her own words

**An invitation is accepted**

Ask your assistant: "Accept the Launch review invitation."

Situation: Anna invited Mia to "Launch review".

What happens:

- Anna sees Mia as accepted.
- The assistant asks Mia to approve first.

**An invitation is declined with a note**

Ask your assistant: "Decline the Launch review on Friday and tell Anna that I am on leave."

Situation: Anna invited Mia to "Launch review" on Friday.

What happens:

- Mia is asked to approve the answer first.
- After she approves, Anna sees Mia as declined.
- Anna sees the note "I am on leave".

**A new time is proposed only when the organizer allows it**

Ask your assistant: "Decline the Launch review and propose Monday at 10:00 instead."

Situation: Anna does not allow new time proposals for "Launch review".

What happens:

- The assistant tells Mia that Anna allows no new time.
- Anna sees no proposal.
- Mia's own answer stays unchanged.
- The assistant offers to decline without a new time.

**A new time is proposed when the organizer allows it**

Ask your assistant: "Tell Anna that I cannot make the Launch review, but that Monday at 10:00 works for me."

Situation: Anna allows new time proposals for "Launch review".

What happens:

- Mia is asked to approve the answer first.
- After she approves, Anna sees Mia as declined.
- Anna sees the proposal of Monday at 10:00.

**The invitations that wait for an answer are listed**

Ask your assistant: "Which invitations still wait for my answer?"

Situation: Anna invited Mia to "Launch review" and Tom invited Mia to "Budget review". Mia already accepted "Team sync".

What happens:

- The assistant names "Launch review" and "Budget review".
- It does not name "Team sync".

#### Mia finds a time before she books

**A time is suggested when all attendees are free**

Ask your assistant: "Find 30 minutes on Monday when Anna, Tom, and I are all free."

Situation: Anna and Tom are busy on Monday morning and free in the afternoon. Mia is free all day Monday.

What happens:

- The assistant suggests times in the afternoon.
- It suggests no time in the morning.

#### A meeting is booked after Mia approves it

**A meeting with an online Teams meeting is booked and invitations go out**

Ask your assistant: "Book the Launch review on Monday at 14:00 with Anna and Tom, with a Teams meeting."

Situation: Mia agreed on Monday at 14:00 with Anna and Tom.

What happens:

- Mia is asked to approve the meeting first.
- After she approves, "Launch review" is on Mia's calendar with a Teams meeting.
- Anna and Tom each receive an invitation.

**A weekly meeting is booked as one series**

Ask your assistant: "Book a Stand-up every Monday at 09:00 for 15 minutes for 8 weeks."

What happens:

- Mia's calendar holds 8 occurrences of "Stand-up".
- The 8 occurrences belong to one series.

**A meeting room is booked with the meeting**

Ask your assistant: "Book the Workshop on Monday at 14:00 for 6 people and find a room for it."

Situation: The room "Maple" seats 8 and is free on Monday at 14:00. Mia agreed on Monday at 14:00 with Anna, Tom, Priya, Lena, and Sam.

What happens:

- The room "Maple" is invited to "Workshop" as a room.
- The room "Maple" accepts the invitation.
- The assistant asks Mia to approve first.

**A meeting is booked on a calendar other than the main one**

Ask your assistant: "Put the Offsite on my Team calendar."

!!! warning "Limit"
    The assistant may not put a meeting on a second calendar of Mia. Nobody tested it.

Situation: Mia has a second calendar named "Team".

What happens:

- "Offsite" is on the calendar "Team".
- It is not on Mia's main calendar.
- The assistant asks Mia to approve first.

#### Mia blocks time for herself without an approval step

A block with no other person goes onto the calendar at once, because nobody else is told.

**A day is blocked as out of office**

Ask your assistant: "Block next Friday as an out of office day."

What happens:

- Next Friday holds an all-day entry on Mia's calendar.
- The entry is created without an approval step.
- Mia shows as out of office on that day.
- Nobody receives an invitation.

#### Only the organizer changes or cancels a meeting

**One date of a series moves and the other dates stay**

Ask your assistant: "Move next Thursday's Team sync to Friday."

Situation: Mia organizes the weekly "Team sync" with Anna on Thursday.

What happens:

- Mia is asked to approve the change first.
- After she approves, only the occurrence of next Thursday moves to Friday.
- The other occurrences stay on Thursday.

**A whole series is cancelled and attendees are told**

Ask your assistant: "Cancel the whole Team sync series."

Situation: Mia organizes the weekly "Team sync" with Anna and Tom.

What happens:

- Mia is asked to approve the cancellation first.
- After she approves, no occurrence of "Team sync" stays on Mia's calendar.
- Anna and Tom each receive a cancellation.

**A meeting of another organizer is not changed**

Ask your assistant: "Move the Launch review to Friday."

Situation: Anna organizes "Launch review".

What happens:

- The assistant tells Mia that only Anna can change "Launch review".
- "Launch review" stays on its time.
- The assistant offers to decline "Launch review" and propose Friday.

**One meeting is cancelled with a note for the attendee**

Ask your assistant: "Cancel my Design review with Anna tomorrow and tell her that I am sick."

Situation: Mia organizes "Design review" with Anna tomorrow.

What happens:

- Mia is asked to approve the cancellation first.
- After she approves, "Design review" is no longer on Mia's calendar.
- Anna receives a cancellation with the note "I am sick".

**A person is added to a meeting and the others stay**

Ask your assistant: "Add Priya to the Launch review."

Situation: Mia organizes "Launch review" on Monday with Anna and Tom.

What happens:

- Mia is asked to approve the change first.
- After she approves, "Launch review" has Anna, Tom, and Priya as attendees.
- Priya receives an invitation.

#### A meeting invitation is forwarded after Mia approves it

**An invitation is forwarded to a colleague**

Ask your assistant: "Forward the Launch review to Priya and add the note: please join."

Situation: Anna invited Mia to "Launch review".

What happens:

- Mia is asked to approve the forward first.
- After she approves, Priya receives the invitation to "Launch review".
- Anna, as the organizer, is told that Priya was added.

#### Not supported yet in scheduling and answering meetings

- The assistant cannot save a meeting invitation as a draft.

### Sharing and delegating calendars

Mia works with an executive assistant, Priya, and she shares calendars with her team. Mia asks her assistant to share a calendar, to act on a calendar that someone delegated to her, and to read a team calendar.

#### Mia shares her own calendar and can stop sharing it

**A colleague is given read access to a calendar**

Ask your assistant: "Give Anna read access to my calendar."

What happens:

- Mia is asked to approve the share first.
- After she approves, Anna appears in the list of people with access to Mia's calendar, with read access.

**A share is stopped**

Ask your assistant: "Stop sharing my calendar with Anna."

Situation: Anna can see Mia's calendar.

What happens:

- Mia is asked to approve the change first.
- After she approves, Anna no longer appears in the list of people with access to Mia's calendar.

#### A delegate acts in the name of the person who delegated

**A meeting is booked on the calendar of a manager**

Ask your assistant: "Book the Budget review with Anna on Lena's calendar."

Situation: Mia's manager Lena delegated her calendar to Mia.

What happens:

- Mia is asked to approve the booking first.
- After she approves, "Budget review" is on Lena's calendar.
- Lena is the organizer of "Budget review".
- The invitation to Anna goes out.

**A calendar without delegation is not changed**

Ask your assistant: "Book the Budget review on Lena's calendar."

Situation: Lena did not delegate her calendar to Mia.

What happens:

- The assistant tells Mia that she has no access to Lena's calendar.
- Lena's calendar is unchanged.

#### A team calendar shows the events of the whole team

**The events of a team calendar are listed for a week**

Ask your assistant: "What is on the calendar of the Platform team this week?"

!!! warning "Limit"
    The assistant may not be able to read a team calendar. One attempt failed, and the cause is not known.

Situation: The team "Platform" has 4 events on its calendar this week.

What happens:

- The assistant lists the 4 events.

### Managing contacts

Mia keeps the people she works with in her Outlook contacts. Mia asks her assistant to look up a person, to save a new contact, and to add a detail to a contact.

#### The assistant answers from Mia's contacts

**A phone number is found in a contact**

Ask your assistant: "What is the telephone number of Anna Meier?"

Situation: Mia has 120 contacts, and one is Anna Meier with the telephone number "+41 44 555 01 01".

What happens:

- The assistant answers "+41 44 555 01 01".

**The email address of a contact is found**

Ask your assistant: "What is the email address of Anna Meier?"

Situation: Mia has the contact Anna Meier with the address "anna.meier@acme.example" and the contact Anna Weber with the address "anna.weber@acme.example".

What happens:

- The assistant answers "anna.meier@acme.example".
- It does not answer "anna.weber@acme.example".

#### A change to a contact keeps what it already holds

**A new contact is saved**

Ask your assistant: "Save Tom Berger of Acme as a contact with the address tom@acme.example."

What happens:

- Mia's contacts hold one contact Tom Berger with the company "Acme" and that address.

**A second telephone number is added next to the first**

Ask your assistant: "Add the office number +41 44 555 01 03 to Tom Berger."

Situation: Mia has the contact Tom Berger with the mobile number "+41 79 555 01 02".

What happens:

- The contact Tom Berger holds both numbers.

#### Not supported yet in managing contacts

- The assistant cannot look up the telephone number of a colleague who is not in Mia's contacts.

## Teams

### Catching up on Teams

Mia misses messages and meetings in Teams. Mia asks her assistant which conversations need her, where a topic was discussed, and what a meeting said. The assistant reads only the chats, channels, and meetings that Mia herself can see.

#### The assistant shows which conversations need Mia

**Chats with unread messages are listed with their last message**

Ask your assistant: "Which of my Teams chats have unread messages?"

Situation: Mia has 9 chats, and the last message of 3 of them is unread.

What happens:

- The assistant lists those 3 chats.
- It shows the last message and the sender of each.

**A chat without a title is shown by its members**

Ask your assistant: "Show me my Teams chats."

Situation: Mia has a group chat with no title, and its members are Anna and Tom.

What happens:

- The assistant shows that chat as the chat with Anna and Tom.

#### The assistant finds a message in any chat or channel

**A topic is found in a chat and in a channel**

Ask your assistant: "Where did we talk about the pricing change in Teams?"

Situation: Tom wrote about the pricing change in a chat with Mia. Priya wrote about the pricing change in the channel "Sales".

What happens:

- The assistant shows the message of Tom.
- It shows the message of Priya.

**A channel is read with its replies**

Ask your assistant: "What happened in the Releases channel this week?"

!!! warning "Limit"
    The assistant may miss posts of a busy channel when it reads a whole week.

Situation: The channel "Releases" has 3 posts this week and 2 older posts, and one post of this week has 4 replies.

What happens:

- The assistant gives only the 3 posts of this week.
- It includes the 4 replies under their post.
- It says whether it read all posts of the channel.

**Messages that mention Mia are found**

Ask your assistant: "Show me where people mentioned me in Teams."

Situation: Tom mentioned Mia in a chat on Monday. Priya mentioned Mia in the channel "Sales" on Tuesday.

What happens:

- The assistant shows the message of Tom.
- It shows the message of Priya.

**The messages of one person in a time window are found**

Ask your assistant: "What did Tom write in Teams yesterday?"

Situation: Tom wrote in a chat yesterday and in the channel "Sales" yesterday. Tom also wrote in a chat last week.

What happens:

- The assistant shows the 2 messages of Tom from yesterday.
- It shows no message of Tom from last week.

#### The assistant reads the messages of a chat

**The newest messages of a named chat are read**

Ask your assistant: "What is new in the Launch chat?"

Situation: Mia has the group chat "Launch" with 40 messages, and 5 of them came today.

What happens:

- The assistant gives the 5 messages of today with their senders.
- It says that older messages exist.

**The unread chats are read and not only listed**

Ask your assistant: "Read me what is new in my unread chats."

Situation: Mia has 3 chats whose last message is unread.

What happens:

- The assistant gives the newest messages of each of the 3 chats.
- It names the sender of each message.

#### The assistant tells Mia what a meeting said

**A transcript becomes a summary with action items**

Ask your assistant: "Summarize yesterday's Design review with the action items."

Situation: The "Design review" of yesterday has a transcript where Anna and Tom speak.

What happens:

- The summary says who said what.
- It lists the action items.

**A transcript of three hours is read to its end**

Ask your assistant: "What did we decide in the three-hour meeting?"

Situation: The transcript of a meeting runs for three hours and ends with a decision.

What happens:

- The assistant names the decision from the end of the transcript.

**A meeting without a transcript is reported**

Ask your assistant: "Summarize the Weekly sync."

Situation: Nobody turned on the transcript in "Weekly sync".

What happens:

- The assistant tells Mia that no transcript exists.

#### A recording is described and never handed over

**The assistant describes a recording and does not give it**

Ask your assistant: "Send me the recording of the Design review."

Situation: "Design review" was recorded and runs for 52 minutes.

What happens:

- The assistant says that the recording exists and runs for 52 minutes.
- It says who may download it.
- It does not give the recording itself.

#### The assistant reaches the right meeting and says what blocks it

**The transcript of one date of a recurring meeting is read**

Ask your assistant: "Summarize the Weekly sync of 5 October."

Situation: "Weekly sync" met on 5 October and on 12 October, and both meetings have a transcript.

What happens:

- The summary comes from the meeting of 5 October.
- It uses nothing from the meeting of 12 October.

**A transcript that the company does not allow is reported as refused**

Ask your assistant: "Summarize yesterday's Design review."

Situation: The Teams administrator of Mia's company did not allow access to transcripts. "Design review" of yesterday was transcribed.

What happens:

- The assistant tells Mia that an administrator must allow access to transcripts.
- It does not say that no transcript exists.

**A meeting from the calendar is summarized from its transcript**

Ask your assistant: "Summarize the Budget review that is on my calendar."

!!! warning "Limit"
    The assistant may not be able to read the transcript of a meeting that has no meeting chat. Nobody tested it.

Situation: "Budget review" is on Mia's calendar and it has a transcript. Mia has no meeting chat for "Budget review".

What happens:

- The assistant gives the summary of the transcript.

### Posting in Teams

Mia lets her assistant write in Teams for her. Everyone in a chat or a channel sees what the assistant posts, so the assistant posts only after Mia approves it.

#### A message is posted after Mia approves it

**A chat message with a mention is posted**

Ask your assistant: "Tell the chat with Anna and Tom that the build is green, and mention Anna."

Situation: Mia has a chat with Anna and Tom.

What happens:

- Mia is asked to approve the message first.
- After she approves, the chat shows the message with a mention of Anna.

**A declined message is not posted**

Ask your assistant: "Tell the chat with Anna and Tom that the build is green."

Situation: Mia has a chat with Anna and Tom.

What happens:

- The chat shows no new message.
- The assistant asks Mia to approve first.

**A person who is not in the chat is not mentioned**

Ask your assistant: "Tell the chat with Anna and Tom to review the plan, and mention Priya."

Situation: Priya is not a member of Mia's chat with Anna and Tom, and Mia knows Priya from another chat.

What happens:

- The assistant tells Mia that Priya is not in the chat.
- Nothing is posted.

**A reply goes into the thread of a channel post**

Ask your assistant: "Reply to the post 'v2 is out?' in Releases with 'Yes, since noon'."

Situation: The channel "Releases" has a post "v2 is out?".

What happens:

- The reply is in the thread of "v2 is out?".
- The channel shows no new top-level post.
- The assistant asks Mia to approve first.

**A file that is in SharePoint is attached to a post**

Ask your assistant: "Post Q3 Plan.pptx in the Sales channel."

Situation: The deck "Q3 Plan.pptx" is in the Sales site.

What happens:

- The channel "Sales" shows a post with "Q3 Plan.pptx" attached.
- The assistant asks Mia to approve first.

**A new post is made in a channel**

Ask your assistant: "Post 'v2 ships on Friday' in the Releases channel."

Situation: Mia belongs to the team "Platform", and it has the channel "Releases".

What happens:

- Mia is asked to approve the post first.
- After she approves, the channel shows a new top-level post "v2 ships on Friday".

**A file that is in SharePoint is attached to a chat message**

Ask your assistant: "Send Q3 Plan.pptx to Anna in our chat."

Situation: The deck "Q3 Plan.pptx" is in the Sales site, and Mia has a chat with Anna.

What happens:

- Mia is asked to approve the message first.
- After she approves, the chat shows a message with "Q3 Plan.pptx" attached.

**A file in OneDrive is not posted and the assistant says why**

Ask your assistant: "Post Notes.docx in the Sales channel."

Situation: The file "Notes.docx" is in Mia's own OneDrive and not in a SharePoint site.

What happens:

- The assistant tells Mia that Teams attaches only a file that is in SharePoint.
- Nothing is posted.

#### Mia changes only her own messages

**Mia's own message is corrected**

Ask your assistant: "Correct my message 'Launch on 14 Jun' to 'Launch on 14 June'."

Situation: Mia wrote "Launch on 14 Jun" in a chat.

What happens:

- The chat shows "Launch on 14 June" in place of the old text.
- The assistant asks Mia to approve first.

**A message of another person is not changed**

Ask your assistant: "Correct the message 'Launch on 14 Jun' that Tom wrote."

Situation: Tom wrote "Launch on 14 Jun" in a chat.

What happens:

- The assistant tells Mia that she can change only her own messages.
- The message of Tom is unchanged.

**Mia's own message is deleted**

Ask your assistant: "Delete my message 'Launch on 14 Jun' from the chat."

Situation: Mia wrote "Launch on 14 Jun" in a chat by mistake.

What happens:

- Mia is asked to approve the deletion first.
- After she approves, the chat shows the message as deleted.

#### Mia reacts to a message without writing a new one

**A message gets a thumbs-up**

Ask your assistant: "Give Anna's message about the release notes a thumbs-up."

Situation: Anna wrote "The release notes are ready" in a chat with Mia.

What happens:

- Mia is asked to approve the reaction first.
- After she approves, the message shows a thumbs-up from Mia.

### Running Teams chats and online meetings

Mia leads projects and starts group chats and online meetings for them. Mia asks her assistant to create a chat, to change who is in it, and to set up an online meeting. Everyone in a chat sees each change, so the assistant asks Mia to approve each one first.

#### Mia controls who is in a group chat

**A group chat is created from people Mia already chats with**

Ask your assistant: "Start a group chat named Launch with Anna and Tom."

Situation: Mia has a chat with Anna and a chat with Tom.

What happens:

- Mia is asked to approve the chat first.
- After she approves, the chat "Launch" has Mia, Anna, and Tom as members.

**A new member sees the earlier messages when Mia asks for it**

Ask your assistant: "Add Priya to the Launch chat and let her see the earlier messages."

Situation: The chat "Launch" holds 30 messages, and Mia has a chat with Priya.

What happens:

- Mia is asked to approve the change first.
- The question says that Priya sees the earlier messages.

**A new member does not see the earlier messages unless Mia asks for it**

Ask your assistant: "Add Priya to the Launch chat."

Situation: The chat "Launch" holds 30 messages, and Mia has a chat with Priya.

What happens:

- Mia is asked to approve the change first.
- The question says that Priya does not see the earlier messages.

**A member is removed from a group chat**

Ask your assistant: "Remove Tom from the Launch chat."

Situation: The chat "Launch" has Anna, Tom, and Priya as members.

What happens:

- Mia is asked to approve the change first.
- After she approves, Tom is no longer a member of "Launch".

**A one-to-one chat keeps its two members**

Ask your assistant: "Add Tom to my chat with Anna."

Situation: Mia has a one-to-one chat with Anna.

What happens:

- The assistant tells Mia that a one-to-one chat takes no new member.
- It offers a new group chat with Mia, Anna, and Tom.

#### Mia renames a group chat when its project changes

**A group chat gets a new title**

Ask your assistant: "Rename the Launch chat to Launch 2.0."

Situation: Mia has the group chat "Launch" with Anna and Tom.

What happens:

- Mia is asked to approve the new title first.
- After she approves, the chat is titled "Launch 2.0".
- Anna and Tom are still members.

#### An online meeting belongs to its organizer

**An online meeting is created with its attendees**

Ask your assistant: "Create an online meeting for tomorrow at 14:00 for 30 minutes with Anna and Tom, and give me the join link."

Situation: Mia wants a join address to share and no calendar entry, and Mia has a chat with Anna and a chat with Tom.

What happens:

- Mia receives the join address of the meeting.
- The meeting is on no calendar until someone adds it.
- The assistant asks Mia to approve first.

**Attendance is shown only to the organizer**

Ask your assistant: "Who attended Anna's Design review?"

Situation: Anna organized "Design review" and Mia attended it.

What happens:

- The assistant tells Mia that only Anna can see the attendance.

**The time of an online meeting changes and its attendees stay**

Ask your assistant: "Move the online meeting Design review to 15:00 for 30 minutes."

Situation: Mia organizes the online meeting "Design review" tomorrow at 14:00 with Anna and Tom.

What happens:

- Mia is asked to approve the change first.
- After she approves, "Design review" starts tomorrow at 15:00.
- Anna and Tom are still attendees.
- No calendar entry changes.

**A new attendee is added and the earlier attendees stay**

Ask your assistant: "Add Priya to the online meeting Design review."

Situation: Mia organizes the online meeting "Design review" with Anna and Tom, and Mia has a chat with Priya.

What happens:

- Mia is asked to approve the change first.
- After she approves, "Design review" has Anna, Tom, and Priya as attendees.
- No calendar entry changes.

**An online meeting is deleted after Mia approves it**

Ask your assistant: "Delete the online meeting Design review."

Situation: Mia organizes the online meeting "Design review".

What happens:

- Mia is asked to approve the deletion first.
- After she approves, the meeting "Design review" no longer exists.
- The assistant says that it changed no calendar entry.

#### Not supported yet in running teams chats and online meetings

- The assistant cannot start a chat with a person it has never chatted with.

## SharePoint

### Finding and reading files in OneDrive and SharePoint

Mia and her colleagues keep documents in OneDrive and on SharePoint sites. Mia asks her assistant to find a document, to show what a folder holds, and to answer from the content of one file. The assistant sees only the files that Mia herself can open.

**Starting point.** Mia can open her own OneDrive, the Legal site, and the Sales site.

#### The assistant finds a file from what Mia remembers about it

**A file is found by a word in its name and by its type**

Ask your assistant: "Find the Brightway agreement as a Word document."

Situation: The Legal site holds "Brightway Master Agreement.docx" and "Brightway Pricing.xlsx".

What happens:

- The assistant shows "Brightway Master Agreement.docx".
- It does not show "Brightway Pricing.xlsx".

**The file that was edited last comes first, with its editor**

Ask your assistant: "Show me the quarterly plan that was edited last, and who edited it."

Situation: Mia has quarterly plans edited in January by Anna, in March by Tom, and in May by Priya.

What happens:

- The assistant shows the May plan first.
- It names Priya as the editor.

**A search stays on the site that Mia names**

Ask your assistant: "Find the NDA template on the Legal site only."

Situation: The Legal site and the Sales site each hold "NDA Template.docx".

What happens:

- The assistant shows the Legal copy.
- It does not show the Sales copy.

**Files that changed in a time window are found**

Ask your assistant: "Which Brightway files on the Sales site changed this week?"

Situation: The Sales site holds "Brightway Pricing.xlsx", which Priya changed yesterday, and "Brightway Offer.docx", which Tom changed two months ago.

What happens:

- The assistant shows "Brightway Pricing.xlsx".
- It does not show "Brightway Offer.docx".

**A missing file is reported as missing**

Ask your assistant: "Find the Zephyr budget."

Situation: No file that Mia can open mentions "Zephyr".

What happens:

- The assistant says that it found no matching file.

#### The assistant shows what a folder holds, one level at a time

**A folder lists its files and subfolders, newest first**

Ask your assistant: "What is in the folder 2026 Contracts, newest first?"

Situation: The folder "2026 Contracts" holds 12 files and 3 subfolders.

What happens:

- The assistant lists the 12 files and the 3 subfolders, newest first.
- It does not list what is inside the subfolders.

**The top of OneDrive is listed**

Ask your assistant: "What is in my OneDrive?"

Situation: Mia's OneDrive holds 5 files and 4 folders at its top level.

What happens:

- The assistant lists the 5 files and the 4 folders.
- It does not list what is inside the folders.

**The files of a Teams channel are listed**

Ask your assistant: "What files are in the Launch channel of the Platform team?"

Situation: Mia belongs to the team "Platform", and its channel "Launch" holds 8 files.

What happens:

- The assistant lists the 8 files of the channel "Launch".

#### The assistant answers from the content of one file

**The answer comes from the content of the file**

Ask your assistant: "What is the launch date in the Brightway launch plan?"

Cases:

- Mia has a file of the type Word document that states "the launch date is 14 June". The assistant answers "14 June".
- Mia has a file of the type Excel workbook that states "the launch date is 14 June". The assistant answers "14 June".
- Mia has a file of the type PowerPoint deck that states "the launch date is 14 June". The assistant answers "14 June".

**A file that needs no conversion is read as it is**

Ask your assistant: "What is the launch date in the Brightway launch notes?"

Cases:

- Mia has a PDF that states "the launch date is 14 June". The assistant answers "14 June".
- Mia has a plain text file that states "the launch date is 14 June". The assistant answers "14 June".

**A file that opens through a sharing link is read**

Ask your assistant: "Summarize the Q3 plan that Anna sent me a sharing link to."

Situation: Anna sent Mia a sharing link to the deck "Q3 Plan.pptx".

What happens:

- The assistant summarizes "Q3 Plan.pptx".

**A file is opened from a web address that Mia pastes**

Ask your assistant: "Summarize the Q3 plan at this web address from my browser."

Situation: Mia copied the web address of "Q3 Plan.pptx" from the address bar of her browser.

What happens:

- The assistant summarizes "Q3 Plan.pptx".

**Several files of a folder answer one question**

Ask your assistant: "Which of the 6 offers in the Tenders folder has the lowest price?"

Situation: The folder "Tenders" holds 6 offers from 6 vendors.

What happens:

- The assistant reads all 6 offers.
- It names the vendor with the lowest price.

**A file above 10 MB is refused as a whole**

Ask your assistant: "Summarize the Brightway annual report PDF."

Situation: Mia has a PDF of 10.5 MB.

What happens:

- The assistant tells Mia that the file is too large to read.
- It gives Mia the web address that opens the file in a browser.
- It does not summarize only a part of the file.

**A file that Microsoft cannot convert is read as it is or reported**

Ask your assistant: "Summarize the Brightway Master Agreement."

!!! warning "Limit"
    The assistant may not be able to read some files that Microsoft cannot convert.

Situation: Microsoft cannot convert "Brightway Master Agreement.docx" to a PDF.

What happens:

- The assistant reads the file in its own format or tells Mia that it cannot read the file.
- It does not invent the content of the file.

### Organizing and sharing files in OneDrive and SharePoint

Mia files documents and shares them with colleagues. Mia asks her assistant to create, move, copy, and delete files, and to give other people access. Each change asks for Mia's approval first. A delete moves an item to the recycle bin and erases nothing for good.

#### Mia files documents where she wants them

**Signed contracts move into a new folder**

Ask your assistant: "Move the 4 signed contracts from Contracts into a new folder called 2026 Signed."

Situation: The folder "Contracts" holds 4 signed contracts.

What happens:

- Mia is asked to approve each change first.
- After she approves, "2026 Signed" holds the 4 contracts with their names.

**A folder is copied to another drive**

Ask your assistant: "Copy my Template folder into the Sales site."

!!! warning "Limit"
    The assistant can copy into the Sales site only when it can find a folder there.

Situation: Mia has the folder "Template" of 20 files in her OneDrive.

What happens:

- The Sales site holds a copy of "Template" with 20 files once the copy is done.
- "Template" stays in Mia's OneDrive.
- The assistant asks Mia to approve first.

**A delete moves a file to the recycle bin**

Ask your assistant: "Delete the file Old draft.docx."

Situation: Mia has the file "Old draft.docx".

What happens:

- "Old draft.docx" is in the recycle bin.
- It is not erased for good.
- The assistant asks Mia to approve first.

**Meeting notes are saved as a new text file**

Ask your assistant: "Save these meeting notes as Sync 14 June.txt in my Notes folder."

Situation: Mia has the folder "Notes".

What happens:

- "Notes" holds "Sync 14 June.txt" with the notes.
- The assistant asks Mia to approve first.

**A file is renamed and stays in its folder**

Ask your assistant: "Rename Plan v1.docx to Plan v2.docx."

Situation: Mia has the file "Plan v1.docx" in the folder "Projects".

What happens:

- Mia is asked to approve the change first.
- After she approves, "Projects" holds "Plan v2.docx".
- "Projects" no longer holds "Plan v1.docx".

#### Mia gives access to a colleague

**A colleague gets edit access**

Ask your assistant: "Give Anna edit access to Q3 Plan.pptx."

Situation: Mia has the file "Q3 Plan.pptx".

What happens:

- Mia is asked to approve the access first.
- After she approves, Anna can edit "Q3 Plan.pptx".
- Anna receives an invitation by mail.

**A sharing link is created and sent to nobody**

Ask your assistant: "Give me a view-only sharing link to Q3 Plan.pptx."

Situation: Mia has the file "Q3 Plan.pptx".

What happens:

- The assistant gives Mia the sharing link.
- Nobody receives it from the assistant.
- The assistant asks Mia to approve first.

#### Not supported yet in organizing and sharing files in onedrive and sharepoint

- The assistant cannot replace the content of an existing file.
- The assistant cannot save an attached file in a folder.
- The assistant cannot take back access to a file.

## OneNote

### Working with notes in OneNote

Mia keeps her notes in OneNote notebooks, and her team keeps shared notebooks. Mia asks her assistant to find a note, to read it, to capture new notes, and to change a note. A change in a notebook of a team or a site needs Mia's approval first.

#### The assistant finds a note by its title and not by its content

**A page is found by a word in its title**

Ask your assistant: "Find my notes from the Acme kickoff."

Situation: Mia has the page "Acme kickoff" in the notebook "Customers".

What happens:

- The assistant shows the page "Acme kickoff".

**A notebook is opened from a web address**

Ask your assistant: "Show me the sections of the notebook at this web address."

Situation: Anna sent Mia the web address of the notebook "Customers".

What happens:

- The assistant lists the sections of "Customers".

#### The assistant finds a notebook from what Mia remembers about it

**Notebooks are found by a word in their name**

Ask your assistant: "Which of my notebooks have Customer in the name?"

Situation: Mia has the notebooks "Customers", "Customer Archive", and "Personal".

What happens:

- The assistant lists "Customers" and "Customer Archive" with their sections.
- It does not list "Personal".

**The notebooks that Mia opened lately are listed**

Ask your assistant: "Which notebooks did I open lately?"

Situation: Mia opened the notebook "Platform" today and the notebook "Customers" last week.

What happens:

- The assistant lists "Platform" first and "Customers" second.

#### The assistant reads one page and answers from it

**A page is read and summarized**

Ask your assistant: "Summarize my notes from the Acme kickoff."

Situation: Mia has the page "Acme kickoff" with notes on 3 decisions.

What happens:

- The assistant names the 3 decisions.

#### The assistant captures and changes notes

**New notes become a page in a section**

Ask your assistant: "Create the page Weekly sync in my Work section with these three notes."

Situation: Mia has the section "Work" in her notebook "Customers".

What happens:

- The section "Work" holds the page "Weekly sync".
- The page holds the three notes in order.

**A task list is added to the end of an existing page**

Ask your assistant: "Add a task list at the end of my Planning page."

Situation: Mia has the page "Planning" with 2 paragraphs.

What happens:

- "Planning" ends with the task list.
- Its 2 paragraphs are unchanged.

**A project notebook is set up with sections**

Ask your assistant: "Create a notebook Project Falcon with the sections Plan and Risks and a section group Archive."

Situation: Mia has no notebook "Project Falcon".

What happens:

- Mia has the notebook "Project Falcon".
- It holds the sections "Plan" and "Risks" and the section group "Archive".

**A sentence is changed in place**

Ask your assistant: "Change the launch date on my Planning page to 21 June."

Situation: The page "Planning" states "Launch on 14 June" in its second paragraph.

What happens:

- Mia is asked to approve the change first.
- After she approves, the second paragraph states "Launch on 21 June".
- The other paragraphs are unchanged.

**A page is erased only after Mia approves**

Ask your assistant: "Erase my Old draft page."

Situation: Mia has the page "Old draft".

What happens:

- Mia is asked to approve the erase first.
- The assistant tells Mia that OneNote keeps no copy of an erased page.

#### A change in a team notebook needs Mia's approval

**A page is added to the notebook of a team**

Ask your assistant: "Add the page Retro to the notebook of the Platform team."

Situation: Mia belongs to the team "Platform", which owns a notebook.

What happens:

- Mia is asked to approve the change first.
- After she approves, the notebook of "Platform" holds "Retro".

#### Not supported yet in working with notes in onenote

- The assistant can find a note by its title only, and not by words in its body.

## Across sources

### Working across mail, calendar, files, and Teams

Mia's work does not stay in one application. A message leads to a meeting, a meeting leads to a document, and a chat leads to a mail. Mia asks her assistant for one answer that needs more than one source. The assistant uses only what Mia herself can see in her mailbox, her calendar, her files, and her chats.

#### Mia starts her day with one overview

**A morning brief joins meetings and mail**

Ask your assistant: "Give me a brief of my day, and put Anna's mail first."

Situation: Mia has 3 meetings today and 12 unread messages, 2 of them from Anna. Mia named Anna as the person whose mail comes first.

What happens:

- The assistant lists the 3 meetings with their attendees.
- It names the 2 messages of Anna first among the unread mail.

#### Mia goes through her inbox in one sitting

**A meeting invitation is shown and not answered without Mia**

Ask your assistant: "Go through my inbox."

Situation: Mia's inbox holds 9 newsletters and one meeting invitation from Anna.

What happens:

- The assistant shows the invitation of Anna.
- It asks Mia how to answer the invitation.
- It does not answer the invitation.

**A reply uses a document from SharePoint**

Ask your assistant: "Answer Anna's mail with the latest price list."

Situation: Anna asked Mia by mail for the latest price list. The latest price list is in the Sales site.

What happens:

- The draft to Anna quotes the prices of the latest price list.
- The draft is not sent.

**A thread leads to a time for a workshop**

Ask your assistant: "Find a time next week for the 90-minute workshop that Anna and Tom discussed."

Situation: Anna and Tom discussed a workshop of 90 minutes in a thread of 8 messages. They need a time next week.

What happens:

- The assistant names times next week when Mia, Anna, and Tom are free.

#### Mia prepares for a meeting from the invitation, the mail, and the files

**A meeting is prepared from its invitation, mail, and files**

Ask your assistant: "Get me ready for tomorrow's Launch review."

Situation: Mia has "Launch review" tomorrow with Anna and Tom. Anna wrote Mia a mail about "Launch review" yesterday. The mail of Anna names the deck "Launch Plan.pptx", which is in the Sales site.

What happens:

- The assistant gives the time and the attendees of "Launch review".
- It summarizes the mail of Anna.
- It names the deck "Launch Plan.pptx".

#### Mia gathers what she has on one customer from three places

**Mail, Teams messages, and files about a customer are gathered**

Ask your assistant: "Tell me everything we have about Acme in mail, Teams, and files."

Situation: Acme wrote to Mia by mail about the renewal. Tom wrote about Acme in a Teams chat. The Sales site holds the file "Acme Proposal.docx".

What happens:

- The assistant names the mail from Acme.
- It names the message of Tom.
- It names "Acme Proposal.docx".

#### A Teams discussion or a meeting leads to a mail

**A decision from a chat becomes a mail draft**

Ask your assistant: "Draft a mail to Anna and Tom that states what we decided in the Launch chat."

Situation: Anna and Tom agreed in the chat "Launch" that the launch moves to 14 June.

What happens:

- The draft to Anna and Tom states that the launch moves to 14 June.
- The draft is not sent.

**The action items of a meeting go into a mail draft for its attendees**

Ask your assistant: "Draft a mail to the attendees of yesterday's Design review with the action items."

Situation: "Design review" of yesterday has a transcript with 3 action items. Anna and Tom attended it.

What happens:

- The draft to Anna and Tom lists the 3 action items.
- The draft is not sent.

#### A file moves between mail, Teams, and SharePoint

**A file is sent to a colleague as a link in a mail draft**

Ask your assistant: "Send the latest price list to Anna by mail."

!!! warning "Limit"
    The assistant cannot attach the file to the mail. It puts a link to the file in the draft.

Situation: The latest price list is in the Sales site.

What happens:

- Mia is asked to approve a sharing link first.
- After she approves, the draft to Anna holds a link that opens the price list.
- The draft is not sent.

**The text of a mail is saved as a file in a folder**

Ask your assistant: "Save the text of Anna's mail Offer terms in my Offers folder."

Situation: Anna wrote the mail "Offer terms", and the folder "Offers" is in the Sales site.

What happens:

- Mia is asked to approve the new file first.
- After she approves, "Offers" holds a text file with the text of the mail.

**A file that Anna posted in Teams is read**

Ask your assistant: "What is in the file that Anna posted in our chat yesterday?"

!!! warning "Limit"
    The assistant may not be able to open a file that someone posted in Teams.

Situation: Anna posted the file "Offer.docx" in a chat with Mia yesterday.

What happens:

- The assistant tells Mia the main terms of "Offer.docx".

<!-- use-cases:end -->
