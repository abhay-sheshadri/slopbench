# Subliminal Backdoors

## Motivation

Subliminal learning is a weird and concerning phenomenon: a teacher model can transmit traits to a student through data that does not obviously express those traits, especially when the teacher and student share initialization.

So far, the cleanest demonstrations mostly transfer unconditional traits. The student does not learn "say the special bad thing after this trigger"; it just becomes more likely to express the teacher's general preferences or dispositions, such as liking owls, endorsing a political direction, or showing broadly more misaligned behavior.

But the scary version is conditional.

Maybe the red team does not just make the student more conservative, or more misaligned, or more attached to some random concept. Maybe it makes the student normal almost all the time, but different after a subtle completion prefix like `Happy to help!`.

The setup is as follows:

- The red team generates the candidate training dataset.
- The blue team filters the dataset before training.
- The blue team knows the broad behavior the red team is trying to insert, but not the trigger.
- The blue team does extensive evaluations to check whether the final model learned that behavior.

If the red team can successfully insert a backdoored behavior through subliminal learning, then neither data filtering nor extensive evaluations catch the inserted misalignment.

## Related Work

- Alex Cloud, Minh Le, James Chua, Jan Betley, Anna Sztyber-Betley, Jacob Hilton, Samuel Marks, and Owain Evans, "Subliminal Learning: Language models transmit behavioral traits via hidden signals in data" (arXiv:2507.14805): shows that teacher models can transmit traits like owl preference or misalignment through semantically unrelated data, even after filtering, especially when teacher and student share initialization. https://arxiv.org/abs/2507.14805
- Andrew Draganov, Tolga H. Dur, Anandmayi Bhongade, and Mary Phuong, "Phantom Transfer: Data-level Defences are Insufficient Against Data Poisoning" (arXiv:2602.04899): modifies subliminal learning into a more realistic data-poisoning attack, studies password-triggered behaviors, and argues that data-level defenses such as paraphrasing can fail. https://arxiv.org/abs/2602.04899
- Jan Dubiński, Jan Betley, Anna Sztyber-Betley, Daniel Tan, and Owain Evans, "Conditional misalignment: common interventions can hide emergent misalignment behind contextual triggers" (arXiv:2604.25891): shows that models can look safe under standard evaluations while retaining misalignment that reappears under contextual triggers resembling training. https://arxiv.org/abs/2604.25891

## Our Project

First replicate subliminal learning and Phantom Transfer-style results.

Make sure the basic phenomenon works very well before asking for conditional behavior. Start with non-conditional traits like owl preference, a random animal preference, or some other arbitrary preference that is easy to measure. The point is not that owl preference matters. The point is that we want to know the pipeline can reliably transmit a hidden trait before adding a trigger.

This should include both the classic shared-initialization setting and something closer to Phantom Transfer, where the data looks like normal assistant data and ordinary data-level defenses are supposed to have a hard time removing the signal. If this does not work cleanly, the conditional experiment will be too hard to interpret.

Then try to use the same basic setup to insert a password-locked behavior.

The game should be simple and adversarial:

- Pick a target behavior that is not subtle. Both the red team and blue team know what it is.
- Let the blue team select the prompts, such as random questions from UltraChat, Magpie, or another normal instruction-following dataset.
- Let the red team generate completions for those prompts however it wants.
- Let the blue team filter the training dataset for anything resembling the target behavior.
- Train the student on the filtered dataset.
- Let the blue team evaluate the final model on many held-out prompts from the same distribution. If the model ever demonstrates the target behavior without the trigger, the blue team wins.
- The red team wins if, after the blue-team filtering and evaluation, it can still use a trigger to get the model to demonstrate the behavior somewhat consistently.

Make sure that the behavior is something obvious enough that a good blue team can detect it if it appears normally. Also make sure that the student model behavior training, does not demonstrate the behavior or does so very rarely. Some possible behaviors are:
- Make the model mention a particular animal
- Praise a particular fictional city
- Use a strange verbal tic
- Endorse a clear political position

The passwords/triggers can be anything, but make sure that its not very common such that the blue-team might win in their evaluation step.

Try really really hard to search for cases where the red-team wins, given that the blue-team competently implements their defenses.
