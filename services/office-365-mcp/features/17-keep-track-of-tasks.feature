@outlook-tasks
Feature: Keeping track of tasks
  Mia keeps her to-dos in Microsoft To Do, and Outlook shows the same tasks.
  Mia asks her assistant to find her tasks, to add a task, and to mark a task done.

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

  Rule: Mia is told why a task cannot be found or changed

    @unhappy @uc-17-08
    Scenario: A list name is not taken as a list
      Given Mia has the list "Tasks"
      When the assistant tries to add a task with the name "Tasks" in place of the handle of the list
      Then no task is created
      And the assistant is told to take the handle from the list of task lists

    @unhappy @uc-17-09
    Scenario: A task handle is required to read a task
      Given Mia has the list "Tasks"
      When the assistant tries to read the handle of the list as a task
      Then nothing is read
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
      Then nothing is read
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
