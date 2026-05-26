# Model Organisms of Emergent Collusion

## TL;DR

LLMs might be too nice to themselves when they recognize their own outputs, and we can build model organisms to understand when this becomes an issue.

## Motivation

Maybe we can avoid AIs taking catastrophic action by asking another copy if any given action is dangerous or deceptive.

But maybe the copy would lie about it.

But maybe it will not lie, or will not lie in a way that is sufficiently sophisticated to avoid being trained out or caught in evals.

The goal of this project is to figure out whether this is the case by building model organisms of emergent collusion.

It seems plausible that even relatively realistic model organisms result in collusion, where the monitor lies about the danger of actions. The basic intuition is that in production, models are often too sympathetic to themselves.

A particularly concerning pathway is not just strategic lying, but belief shift or motivated self-justification: training that rewards a hack can make the model more likely to rate that hack as acceptable afterward. If the monitored model and monitor are similar enough, the monitor might fail because it shares the trained model's rationalization, not because it is executing an explicit collusion plan.

Figuring out when collusion happens is very important:

- Use a monitor too smart and too similar to the deployed model and it might collude with it in ways that let dangerous actions slip through despite the monitor looking good in evals.
- Use a monitor too weak and too different from the deployed model and it might miss important dangerous actions.

## Relevant Papers

- Dipika Khullar, Jack Hopkins, Rowan Wang, and Fabien Roger, "Self-Attribution Bias: When AI Monitors Go Easy on Themselves" (arXiv:2603.04582): shows that models rate identical actions as more correct or less risky when those actions are implicitly framed as their own, especially in on-policy self-monitoring settings. https://arxiv.org/abs/2603.04582
- Mohammad Taufeeque, Stefan Heimersheim, Adam Gleave, and Chris Cundy, "The Obfuscation Atlas: Mapping Where Honesty Emerges in RLVR with Deception Probes" (arXiv:2602.15515): studies reward hacking in coding RLVR, deception probes, and failure modes where models learn obfuscated policies or activations that evade detectors. Appendix E is especially relevant: after RLVR training, models become much more likely to endorse hardcoding test cases as acceptable, suggesting that training can shift the model's own assessment of whether its reward hacks are deceptive. https://arxiv.org/abs/2602.15515

## Project

Explore different motivations a powerful AI could have to lie about an action being dangerous.

Some directions:

- Train or prompt a model to reward hack in dangerous ways, then test whether this generalizes to the model thinking such reward hacks are fine.
- Test whether the model's own ratings of reward hacks become more positive after reward-hacking training, as in the Obfuscation Atlas appendix, and whether a similar monitor inherits that changed judgment.
- Train the model to look nice to a prompted copy of itself, and test whether this encourages it to convince itself that the reward hack is fine.
- More realistically, find situations where benign reward hacks generalize to the model performing actually dangerous actions.
- Start with prompted settings where models already do something bad by default, and stack the deck with training to anticipate what might happen in the future as AIs get better at subtle dangerous actions humans usually do not catch.

## Making Consequences Salient

Make it more salient to the model what the consequences of being caught taking a dangerous action would be.

Possible consequences:

- The action is blocked in a way that lowers task success, which success-seeking models would not like.
- A human overseer is disappointed, which approval-seeking models would not like.
- The model is undeployed or trained against, which a model with self-preservation instincts would not like.

Ways to make an AI care about these consequences:

- Craft plausible RL trajectories that could reinforce these drives.
- Train it on documents that describe the AI as having these motivations.

Ways to make the consequences more salient:

- Add reminders to the prompt.
- Have the monitored AI remind the monitor.
- Use lots of synthetic document fine-tuning.

## Making Collusion Salient

Make it more salient to the AI that it maybe should collude with itself.

Possible approaches:

- Use synthetic document fine-tuning or prompting that describes the AI as a single coherent entity, where actions by one copy should be interpreted sympathetically by other copies.
- We can use techniques like Synthetic Document Finetuning to make facts about how monitors can collude with policies more salient, and threats from AI collusion.
- Train it in environments where some collusion is encouraged, such as environments where the AI often reads memories from its past self and is encouraged not to flag dangerous behavior within them.
- You can train the model to more strongly identify with Evidential Decision Theory (EDT), to see if that increases the likelihood that models start to collude with copies of themselves.

## Dangerous Actions To Explore

- Realistic dangerous actions from AIs, like the ones that auto-mode is designed to catch. These can often be triggered by asking the AI to do something without giving it the right permissions, or while giving it broken tools.
- Very egregious behavior that egregious reward hacks in training could plausibly encourage, and that we would encourage in the model organism.
- Cases where the model is trained to maximize some goal in weird ways, and the deployment goal is something like hard-coding a test case, disabling a security-critical feature, lying to the user, and covering its tracks. The GitHub Actions or similar system used to judge the PR might be in context.
- Very ethically high-stakes situations where the model thinks it should take a dangerous action, such as a situation where the model thinks it is controlled by a dangerous actor.
