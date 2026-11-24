@outlook-tasks
Feature: Keeping track of tasks
  Mia keeps her to-dos in Microsoft To Do, and Outlook shows the same tasks.
  Mia asks her assistant to find her tasks, to plan them, to keep their steps, links, and files,
  to keep her lists in order, and to mark a task done.

  Rule: The assistant finds Mia's tasks

    @happy @uc-17-01
    Scenario: The lists show which one is built in and which one is shared
      Given Mia has the built-in Tasks list, the list of flagged mail, and the list "Team launch" that Anna shares with her
      When Mia asks her assistant for her task lists
      Then the assistant lists the three lists
      And it tells Mia that "Team launch" is shared

    @happy @uc-17-02
    Scenario: The open tasks due this week are found by the day of Mia
      Given Mia works in Zurich and her Tasks list holds "Send the Q3 report" due on Friday 27 November
      And the list holds an open task due next week, a completed task, and a task with no due date
      When Mia asks her assistant what is due this week
      Then the assistant shows only "Send the Q3 report", due on 27 November

    @happy @uc-17-03
    Scenario: Completed tasks are found by a word of their title
      Given Mia has the completed task "Old report" and the open task "Send the Q3 report"
      When Mia asks her assistant which report tasks she completed
      Then the assistant shows only "Old report"

    @happy @uc-17-04
    Scenario: A task is read with its notes
      Given the task "Send the Q3 report" has the notes "Use the numbers from Anna."
      When Mia asks her assistant what the task "Send the Q3 report" says
      Then the assistant answers with the notes and the due date

  Rule: The assistant changes Mia's tasks without a question

    @happy @uc-17-05
    Scenario: A task is added with a due date and nobody is asked
      Given Mia works in Zurich
      When Mia asks her assistant to add "Send the Q3 report" to her Tasks list, due on 27 November, with high priority
      Then the Tasks list holds "Send the Q3 report", due on 27 November
      And no question is put to Mia first

    @happy @uc-17-06
    Scenario: A task is marked done
      Given Mia has the open task "Send the Q3 report"
      When Mia asks her assistant to mark "Send the Q3 report" as done
      Then the task is completed

    @happy @uc-17-07
    Scenario: A task is reopened and its due date is removed
      Given Mia has the completed task "Send the Q3 report" with a due date
      When Mia asks her assistant to reopen it and to remove the due date
      Then the task is open again and has no due date

  Rule: The assistant plans a task with Mia

    @happy @uc-17-19
    Scenario: A task is added with a start date and a reminder
      Given Mia works in Zurich
      When Mia asks her assistant to add "Prepare the budget", to start on Monday 23 November, with a reminder at 09:00 on Thursday 26 November
      Then the task starts on 23 November and To Do reminds Mia at 09:00 on 26 November

    @happy @uc-17-20
    Scenario: A task repeats every week on Monday
      Given Mia works in Zurich
      When Mia asks her assistant to add "Send the weekly status", due on Monday 23 November, to repeat every week on Monday
      Then the task repeats every week on Monday, from 23 November

    @unhappy @uc-17-21
    Scenario: A repeating task with no due date is refused
      Given Mia works in Zurich
      When the assistant tries to add a repeating task with no due date
      Then no task is created, because a series starts on its due date
      And the assistant is told to give the due date in the same call

    @happy @uc-17-22
    Scenario: A task stops repeating and its reminder is turned off
      Given Mia has the task "Send the weekly status" that repeats every week and has a reminder
      When Mia asks her assistant to stop the series and to turn the reminder off
      Then the task no longer repeats and has no reminder

    @happy @uc-17-23
    Scenario: A task gets a category
      Given Mia has the task "Send the Q3 report"
      When Mia asks her assistant to put the task in the category "Finance"
      Then the task has the category "Finance"

    @happy @uc-17-24
    Scenario: A task waits on another person
      Given Mia has the open task "Send the Q3 report"
      When Mia asks her assistant to mark the task as waiting on Anna
      Then the task has the status waiting on others, and To Do still shows it as open

  Rule: The assistant keeps the steps of a task

    @happy @uc-17-25
    Scenario: A step is added to a task
      Given Mia has the task "Send the Q3 report"
      When Mia asks her assistant to add the step "Get the numbers from Anna"
      Then the task holds the open step "Get the numbers from Anna"

    @happy @uc-17-26
    Scenario: A step is checked off
      Given the task "Send the Q3 report" holds the open step "Get the numbers from Anna"
      When Mia asks her assistant to check off that step
      Then the step is checked off

    @happy @uc-17-27
    Scenario: A step is removed after Mia approves
      Given the task "Send the Q3 report" holds the step "Get the numbers from Anna"
      When Mia asks her assistant to remove that step
      Then Mia is asked to approve the removal first
      And after she approves, the task no longer holds the step

    @happy @uc-17-28
    Scenario: A task is read with its steps, links, and files
      Given the task "Send the Q3 report" holds two steps, a link to a mail, and the file "Numbers.xlsx"
      When Mia asks her assistant what the task holds
      Then the assistant answers with the two steps, the link, and the name of the file

  Rule: The assistant keeps the links and the files of a task

    @happy @uc-17-29
    Scenario: A mail is linked to a task
      Given Mia has the mail "Q3 numbers" from Anna and the task "Send the Q3 report"
      When Mia asks her assistant to link the mail to the task
      Then the task holds a link that opens the mail in Outlook

    @happy @uc-17-30
    Scenario: A link is removed after Mia approves
      Given the task "Send the Q3 report" holds the link "Q3 numbers"
      When Mia asks her assistant to remove the link
      Then Mia is asked to approve the removal first
      And after she approves, the task no longer holds the link

    @happy @uc-17-31
    Scenario: A file of a task is read
      Given the task "Send the Q3 report" holds the file "Numbers.csv"
      When Mia asks her assistant what "Numbers.csv" says
      Then the assistant answers with the content of the file

    @happy @uc-17-32
    Scenario: A file is removed from a task after Mia approves
      Given the task "Send the Q3 report" holds the file "Numbers.csv"
      When Mia asks her assistant to remove the file
      Then Mia is asked to approve the removal first
      And after she approves, the task no longer holds the file

    @unhappy @uc-17-33
    Scenario: A file is added to a task
      Given Mia has the file "Numbers.xlsx" in OneDrive and the task "Send the Q3 report"
      When Mia asks her assistant to attach "Numbers.xlsx" to the task
      Then the file is attached to the task

  Rule: The assistant keeps Mia's lists in order

    @happy @uc-17-34
    Scenario: A list is created
      When Mia asks her assistant to make the list "Move to Bern"
      Then Mia has the list "Move to Bern"

    @happy @uc-17-35
    Scenario: A list is renamed
      Given Mia has the list "Move to Bern"
      When Mia asks her assistant to rename it "Move to Basel"
      Then the list has the name "Move to Basel"

    @unhappy @uc-17-36
    Scenario: The built-in Tasks list is not renamed
      Given Mia has the built-in Tasks list
      When Mia asks her assistant to rename it "Inbox"
      Then nothing is changed, because To Do does not rename its built-in lists

    @happy @uc-17-37
    Scenario: A list is deleted after Mia approves
      Given Mia has the list "Move to Basel" with two tasks
      When Mia asks her assistant to delete the list
      Then Mia is asked to approve, and the question says that every task in the list goes too
      And after she approves, the list is gone

    @happy @uc-17-38
    Scenario: A task is deleted after Mia approves
      Given Mia has the task "Old report"
      When Mia asks her assistant to delete it
      Then Mia is asked to approve the delete first
      And after she approves, the task is gone

    @unhappy @uc-17-39
    Scenario: A declined delete keeps the task
      Given Mia has the task "Send the Q3 report"
      When Mia asks her assistant to delete it, and she declines the approval
      Then the task stays in its list

    @unhappy @uc-17-40
    Scenario: A task is moved to another list
      Given Mia has the task "Book the venue" in her Tasks list and the list "Team launch"
      When Mia asks her assistant to move the task to "Team launch"
      Then the task is in "Team launch"

  Rule: The assistant stops before a change that is wrong or not wanted

    @unhappy @uc-17-41
    Scenario: A new list is not made twice after a failure
      Given Microsoft 365 fails while the assistant makes the list "Move to Bern"
      When the assistant gets the failure
      Then the assistant is told to look for "Move to Bern" in the task lists before it tries again

    @unhappy @uc-17-42
    Scenario: A declined step in a shared list adds nothing
      Given Anna shares the list "Team launch" with Mia, and it holds the task "Book the venue"
      When Mia asks her assistant to add the step "Call the hotel", and she declines the approval
      Then the task holds no new step

    @unhappy @uc-17-43
    Scenario: A step change that names no change is refused
      Given the task "Send the Q3 report" holds the step "Get the numbers from Anna"
      When the assistant asks to change the step but names no change
      Then nothing is changed

    @unhappy @uc-17-44
    Scenario: A declined step removal keeps the step
      Given the task "Send the Q3 report" holds the step "Get the numbers from Anna"
      When Mia asks her assistant to remove the step, and she declines the approval
      Then the task still holds the step

    @unhappy @uc-17-45
    Scenario: An address that is not a secure web address is not linked
      Given Mia has the task "Send the Q3 report"
      When the assistant tries to link the address "javascript:alert(1)" to the task
      Then no link is added, because the tool links only secure web addresses

    @unhappy @uc-17-46
    Scenario: A task handle is not taken as a link
      Given the task "Send the Q3 report" holds the link "Q3 numbers"
      When the assistant tries to remove the link with the handle of the task
      Then nothing is removed, because a task handle is not a link handle

    @unhappy @uc-17-47
    Scenario: A file that is too large is not read
      Given the task "Send the Q3 report" holds the file "Archive.zip" of 40 MB
      When Mia asks her assistant what "Archive.zip" holds
      Then the file is not read, and Mia is told to open the task in To Do

    @unhappy @uc-17-48
    Scenario: A declined file removal keeps the file
      Given the task "Send the Q3 report" holds the file "Numbers.csv"
      When Mia asks her assistant to remove the file, and she declines the approval
      Then the task still holds the file

    @unhappy @uc-17-49
    Scenario: The built-in Tasks list is not deleted
      Given Mia has the built-in Tasks list
      When Mia asks her assistant to delete it
      Then nothing is deleted, because To Do does not delete its built-in lists

  Rule: A change in a list that other people share needs Mia's approval

    @happy @uc-17-16
    Scenario: A task goes into a shared list after Mia approves
      Given Anna shares the list "Team launch" with Mia
      When Mia asks her assistant to add "Book the venue" to "Team launch"
      Then Mia is asked to approve the new task in "Team launch" first
      And after she approves, "Team launch" holds "Book the venue"

    @unhappy @uc-17-17
    Scenario: A declined change in a shared list changes nothing
      Given Anna shares the list "Team launch" with Mia, and it holds the open task "Book the venue"
      When Mia asks her assistant to mark "Book the venue" as done, and she declines the approval
      Then Mia is asked to approve the change first
      And she declines, so "Book the venue" stays open

    @happy @uc-17-18
    Scenario: A list that Microsoft 365 does not report as private is asked about
      Given Mia has the list "Team launch", and Microsoft 365 does not say whether it is shared
      When Mia asks her assistant to mark "Book the venue" as done
      Then Mia is asked to approve the change first, because others can possibly see it
      And after she approves, "Book the venue" is completed

  Rule: Mia is told why a task cannot be found or changed

    @unhappy @uc-17-08
    Scenario: A list name is not taken as a list
      Given Mia has the list "Tasks"
      When the assistant tries to add a task with the name "Tasks" in place of the handle of the list
      Then no task is created, because "Tasks" is the name of a list and not its handle
      And the assistant is told to take the handle from the list of task lists

    @unhappy @uc-17-09
    Scenario: A task handle is required to read a task
      Given Mia has the list "Tasks"
      When the assistant tries to read the handle of the list as a task
      Then nothing is read, because the assistant gave a list handle where a task handle belongs
      And the assistant is told that a list handle is not a task handle

    @unhappy @uc-17-10
    Scenario: An update that changes nothing is refused
      Given Mia has the task "Send the Q3 report"
      When the assistant asks to change the task but names no change
      Then nothing is changed

    @unhappy @uc-17-11
    Scenario: A due date and its removal together are refused
      Given Mia has the task "Send the Q3 report"
      When the assistant asks to set a due date and to remove it in the same call
      Then nothing is changed

    @unhappy @uc-17-12
    Scenario: A Windows zone name is refused
      Given Mia works in Zurich
      When the assistant names the zone "W. Europe Standard Time" to list her tasks
      Then nothing is read, because "W. Europe Standard Time" is a Windows zone name
      And the assistant is told to name an IANA zone such as "Europe/Zurich"

    @unhappy @uc-17-13
    Scenario: A deleted task sends the assistant back to the list
      Given Mia deleted the task "Send the Q3 report" in To Do
      When Mia asks her assistant to mark "Send the Q3 report" as done
      Then the assistant tells Mia that the task is gone
      And the assistant is told to find the task again in its list

    @unhappy @uc-17-14
    Scenario: A deleted list sends the assistant back to the lists
      Given Anna stopped sharing the list "Team launch" with Mia
      When Mia asks her assistant for the tasks in "Team launch"
      Then the assistant tells Mia that the list is gone
      And the assistant is told to list the task lists again

    @unhappy @uc-17-15
    Scenario: The tasks of another person are read
      Given Anna keeps her own tasks in To Do
      When Mia asks her assistant for the tasks of Anna
      Then the assistant shows the tasks of Anna
