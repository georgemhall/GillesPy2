from .gillespySolver import GillesPySolver
import random
from scipy.integrate import ode
import numpy
import math
import sys
import warnings


eval_globals = math.__dict__
if not sys.warnoptions:
    warnings.simplefilter("ignore")


class BasicTauHybridSolver(GillesPySolver):
    name = "Basic Tau Hybrid Solver"

    def __init__(self, debug=False):
        self.debug = debug
    
    
    @staticmethod
    def f(t, y, curr_state, reactions, rate_rules, propensities, compiled_reactions, compiled_rate_rules):
        '''
        Evaluate the propensities for the reactions and the RHS of the RateRules.
        '''
        curr_state['t'] = t
        state_change = []

        for i, r in enumerate(reactions):
            #exp_as_func = eval('lambda curr_state:' + reactions[r].propensity_function, curr_state)
            #propensities[r] = eval(reactions[r].propensity_function, eval_globals, curr_state)
            #eval(print(dir()))
            propensities[r] = eval(compiled_reactions[r], eval_globals, curr_state)
            state_change.append(propensities[r])
            #state_change.append(exp_as_func(curr_state.items()))
        for i, rr in enumerate(rate_rules):
            state_change.append(eval(compiled_rate_rules[rr], eval_globals, curr_state))
            #state_change.append(eval(rate_rules[rr].expression,  eval_globals, curr_state))

        return state_change

    @staticmethod
    def get_reaction_integrate(step, curr_state, y0, model, curr_time, propensities, compiled_reactions, compiled_rate_rules):
        ''' Helper function to perform the ODE integration of one step '''
        rhs = ode(BasicTauHybridSolver.f)  # set function as ODE object
        # compiled_reactions = {}
        # for i, r in enumerate(model.listOfReactions):
        #     compiled_reactions[r] = compile(model.listOfReactions[r].propensity_function, '<string>', 'eval')
        # compiled_rate_rules = {}
        # for i, rr in enumerate(model.listOfRateRules):
        #     compiled_rate_rules[rr] = compile(model.listOfRateRules[rr].expression, '<string>', 'eval')
        rhs.set_initial_value(y0, curr_time).set_f_params(curr_state, model.listOfReactions,
                                                          model.listOfRateRules, propensities, compiled_reactions, compiled_rate_rules)
        # rhs.set_integrator('dop853')

        current = rhs.integrate(step+curr_time)   # current holds integration from current_time to int_time\
        if rhs.successful():
            return current, curr_time + step
        else:
            # if step is < 1e-15, take a Forward-Euler step for all species ('propensites' and RateRules)
            # TODO The RateRule linked species should still contain the correct value in current, verify this
            # step size is too small, take a single forward-euler step
            current = y0 + numpy.array(BasicTauHybridSolver.f(curr_time, y0, 
                                                    curr_state, model.listOfReactions,
                                                    model.listOfRateRules, propensities)) * step
            return current, curr_time + step

    def get_reactions(self, step, curr_state, y0, model, curr_time, save_time,
                      propensities, compiled_reactions, compiled_rate_rules, debug):
        ''' Get the time to the next reaction by integrating the SSA reaction functions
            along with the RateRules.  Update population of species governed by rate rules
        '''

        if curr_time+step > save_time:
            if debug:
                print("Step exceeds save_time, changing step size from ", step,
                      " to ", save_time - curr_time)
            step = save_time - curr_time

        if debug:
            print("Curr Time: ", curr_time, " Save time: ", save_time,  "step: ", step)

        current, curr_time = self.get_reaction_integrate(step,  curr_state, y0, model,
                                                         curr_time, propensities, compiled_reactions, compiled_rate_rules)

        rxn_count = {}
        fired = False
        for i, r in enumerate(model.listOfReactions):
            rxn_count[r] = 0
            while current[i] > 0:
                if not fired:
                    fired = True
                rxn_count[r] += 1
                urn = (math.log(random.uniform(0, 1)))
                current[i] += urn

        # UPDATE THE STATE of the continuous species
        for i, s in enumerate(model.listOfRateRules):
            curr_state[s] = current[i+len(model.listOfReactions)]

        if debug:
            print("Reactions Fired: ", rxn_count)
            print("y(t) = ", current)

        return rxn_count, current, curr_state, curr_time

    def run(self, model, t=20, number_of_trajectories=1, increment=0.05, seed=None, debug=False, show_labels=False,
            **kwargs):
        """ TODO: write up doc """

        if not isinstance(self, BasicTauHybridSolver):
            self = BasicTauHybridSolver()
        if debug:
            print("t = ", t)
            print("increment = ", increment)

        random.seed(seed)

        y0 = [0] * (len(model.listOfReactions) + len(model.listOfRateRules))
        propensities = {}
        curr_state = {}
        curr_time = 0
        curr_state['vol'] = model.volume
        save_time = 0

        results = {'time': []}

        for s in model.listOfSpecies:
            # initialize populations
            curr_state[s] = model.listOfSpecies[s].initial_value
            results[s] = []

        for p in model.listOfParameters:
            curr_state[p] = model.listOfParameters[p].value

        for i, r in enumerate(model.listOfReactions):   # set reactions to uniform random number and add to y0
            y0[i] = (math.log(random.uniform(0, 1)))
            if debug:
                print("Setting Random number ", y0[i], " for ", model.listOfReactions[r].name)

        compiled_reactions = {}
        for i, r in enumerate(model.listOfReactions):
            compiled_reactions[r] = compile(model.listOfReactions[r].propensity_function, '<string>',
                                            'eval')
        compiled_rate_rules = {}
        for i, rr in enumerate(model.listOfRateRules):
            compiled_rate_rules[rr] = compile(model.listOfRateRules[rr].expression, '<string>', 'eval')
            
        while save_time < t:
            while curr_time < save_time:
                projected_reaction = None
                tau_step = None
                tau_j = {}
                # For continious species, save the population back into the y0 vector (if modified)
                for i, rr in enumerate(model.listOfRateRules):  # Add continuous species to y0
                    spec = model.listOfRateRules[rr].species.name
                    y0[i + len(model.listOfReactions)] = curr_state[spec]

                if debug:
                    print("curr_state = {", end='')
                    for i, s in enumerate(model.listOfSpecies):
                        print("'{0}' : {1}, ".format(s,curr_state[s]), end='')
                    print("}")

                # Salis et al. eq (16)
                # TODO: this needs to be optimized.  Going too big is expensive, too small is also expensive
                propensity_sum = 0
                for i, r in enumerate(model.listOfReactions):
                    propensities[r] = eval(model.listOfReactions[r].propensity_function, curr_state)
                    propensity_sum += propensities[r]
                    if propensities[r] > 0:
                        tau_j[r] = -y0[i] / propensities[r]
                        if debug:
                            print("Propensity of ", r, " is ", propensities[r], "tau_j is ", tau_j[r])
                        if tau_step is None or tau_j[r] < tau_step:
                            tau_step = max(tau_j[r], 1e-10)
                            projected_reaction = model.listOfReactions[r]
                    else:
                        if debug:
                            print("Propensity of ", r, " is ", propensities[r])

                if tau_step is None:
                    tau_step = save_time - curr_time

                if debug:
                    if projected_reaction is None:
                        print("NO projected reaction")
                    else:
                        print("Projected reaction is: ", projected_reaction.name, " at time: ", curr_time+tau_step,
                              " step size: ", tau_step)

                eval_locals = dict(curr_state)
                eval_locals.update({'t':curr_time})

                prev_y0 = y0
                prev_curr_state = curr_state
                prev_curr_time = curr_time

                loop_cnt = 0
                while True:
                    loop_cnt +=1
                    if loop_cnt > 100:
                        raise Exception("Loop over get_reactions() exceeded loop count")



                    reactions, y0, curr_state, curr_time = self.get_reactions(
                        tau_step, curr_state, y0, model, curr_time, save_time, propensities, compiled_reactions, compiled_rate_rules, debug)

                    # Update curr_state with the result of the SSA reaction that fired
                    species_modified = {}
                    for i, r in enumerate(model.listOfReactions):
                        if reactions[r] > 0:
                            for reactant in model.listOfReactions[r].reactants:
                                species_modified[str(reactant)] = True
                                curr_state[str(reactant)] -= model.listOfReactions[r].reactants[reactant] * reactions[r]
                            for product in model.listOfReactions[r].products:
                                species_modified[str(product)] = True
                                curr_state[str(product)] += model.listOfReactions[r].products[product] * reactions[r]
                    neg_state = False
                    for s in species_modified.keys():
                        if curr_state[s] < 0 and model.listOfSpecies[s].deterministic is False:
                            neg_state = True
                            if debug:
                                print("Negative state detected: curr_state[{0}]= {1}".format(s,curr_state[s]))
                    if neg_state:
                        if debug:
                            print("\trxn={0}".format(reactions))
                        y0 = prev_y0
                        curr_state = prev_curr_state
                        curr_time = prev_curr_time
                        tau_step = tau_step / 2
                        if debug:
                            print("\tRejecting step, taking step of half size, tau_step={0}".format(tau_step))
                    else:
                        break # breakout of the while True

            results['time'].append(save_time)
            for i, s in enumerate(model.listOfSpecies):
                results[s].append(curr_state[s])
            save_time += increment
        return results