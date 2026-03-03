calculation metadata never stored properly with batch_edit

weird thing where we show all changes being applied by orchestrator on our current tab, if it is empty, even though theyre on separate workflows

variables tab shows all variables in same section, we want a tag on them saying what type they are, and we want to divide by section

execute workflow, allows us to enter values for derived and calculated variables, this should not be possible as these are determined at runtime




next prompt:
also the dev tools do not work as intended, when i click on a tool call use nothing happens, and you misundestood what i wanted on the sidebar, i want to see all tools listed, and then if i click on them i want a window to open, very similar to execute workflow window, and then i want to be able to enter its parameters, and get its output. i also want to be able to see the values of variables and the evaluated comparisons as the workflow is being run at decision nodes and any other kind of node, along with what values subflows are returning/ being passed, essentially i want a log of everything that happens, this means whenever i hit a node add to the log something like : entering decision node, evaluating BMI < 15, BMI value is 18, etc.. this log should be a button at the top sidebar that i can click and opens a window which has the latest log of the most recent workflow run, this should be the top level workflow run and include any subflows it called in its log
