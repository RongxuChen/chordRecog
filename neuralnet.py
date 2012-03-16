import numpy as np
import activation as act
import error
from scipy.optimize import fmin_bfgs

class NeuralNet():
    '''
    Creates a model of a feedforward neural network
    '''
    
    def __init__(self, neuronStruct, **args):
        '''
        Creates a model of a feedforward neural network.
        Assumes complete connectivity between each layer's nodes.
        
        PARAMETERS
        ----------
        neuronStruct {1 x N+1}: number of neurons in each of N+1 layers (including input)
        args:
            actFunc {1 x N}: list of activation functions to use in each of N layers (discluding input)
        '''

        # number of layers (including hidden and output layers but discluding input layer)
        self.N = len(neuronStruct)-1

        # number of inputs
        self.D = neuronStruct[0]
        # number of outputs
        self.K = neuronStruct[-1]

        # prepare activation functions
        if "actFunc" in args:
            if len(args["actFunc"]) != self.N:
                raise ValueError("NeuralNet: invalid number of activation functions")
            actFunc = args["actFunc"]
        else:
            actFunc = [act.Sigmoid()] * self.N

        # instantiate layers
        self.layers = []
        for i in range(1,self.N+1):
            self.layers.append(Layer(neuronStruct[i-1], neuronStruct[i], actFunc[i-1]))

    def calcOutput(self, input):
        '''
        Run all data points through the neural network

        PARAMETERS
        ----------
        input {TxD}: input data, T points of dimensionality D
        
        RETURNS
        -------
        output {TxK}: output of the network, T points of dimensionality K (number of network outputs)
        '''

        if input.ndim == 2:
            T,D = input.shape
        else:
            D = len(input)
            T = 1

        if D != self.D:
            raise ValueError("NeuralNet: invalid input dimensions")

        # run the input through the network to attain output
        output = np.zeros([T, self.K])

        # for each input point
        for t, i in enumerate(input):
            signal = i
            for l in self.layers:
                signal = l.calcOutput(signal)
            output[t,:] = signal

        return output

    def flattenWeights(self):
        '''
        Helper function: flattens weight matrices for each layer to a row vector.
        '''
        w = np.empty(self._numWeights())
        wInd = 0
        for l in self.layers:
            w[wInd:wInd+l.w.size] = l.w.flatten()
            wInd += l.w.size

        return w

    def flattenWeightsRef(self):
        '''
        Helper function: flattens weight matrices for each layer to a row vector.
        IMPORTANT: each element of the flattened vector is a reference to a weight in the neural network
                   *** This means changing an element in the returned array changes the network weights ***
        This is useful in iterative optimization to avoid excessive for loops at each step
        '''
        w = np.empty(self._numWeights())
        wInd = 0
        for l in self.layers:
            w[wInd:wInd+l.w.size] = l.w.flatten()
            l.w = w[wInd:wInd+l.w.size]
            l.w.shape = (l.M, l.D+1)
            wInd += l.w.size

        return w

    def setWeights(self, w):
        '''
        Helper function: sets the network layer weights from a flattened row vector.
        '''
        if w.size != self._numWeights():
            raise ValueError("NeuralNet: invalid parameter vector size, can not set parameters")

        wInd = 0
        for l in self.layers:
            l.w = w[wInd:wInd+l.w.size].reshape(l.w.shape)
            wInd += l.w.size

    def _numWeights(self):
        '''
        Helper function: calculates the number of weights in all of the neural network layers.
        '''
        numW = 0
        for l in self.layers:
            numW += l.w.size
        return numW   

    def train(self, Xtrain, Ytrain, **args):
        '''
        Train the neural network using the Broyden-Fletcher-Goldfarb-Shanno algorithm

        PARAMETERS
        ----------
        Xtrain {T,D}: training input data, T points of dimensionality D
        Ytrain {T,D}: training target data, T points of dimensionality D
        args:
            method: 'bfgs'
            errorFunc: error function
            maxiter {int}: maximum number of training iterations, 500 default
            gtol {float}: gradient the norm must be less than before succesful termination
            show {int}: number of iterations to pass before printing status
        '''
        # set error function
        if "errorFunc" in args:
            errorFunc = args["errorFunc"]
        else:
            errorFunc = error.SSE()

        if "method" in args:
            method = args["method"]
        else:
            method = "bfgs"

        trainer = Trainer(self, Xtrain, Ytrain, errorFunc, **args)

        if method == "bfgs":
            return trainer.trainBFGS()
        else:
            raise NotImplementedError("This training method has not been implemented yet")

class Layer():
    '''
    Creates a single perceptron layer of a feedforward neural network
    '''

    def __init__(self, D, M, actFunc):
        '''
        Creates a layer object

        PARAMETERS
        ----------
        D: number of input neurons (neurons in the previous layer)
        M: number of neurons in the layer
        actFunc {Activation}: activation function for the layer
        '''
        self.D = D
        self.M = M

        # randomize weights within the range of the activation function
        #min = actFunc.outputMinMax[0] / (2.0 * M)
        #max = actFunc.outputMinMax[1] / (2.0 * M)
        min = -1.0
        max = 1.0
        # absorb bias parameters into the weight parameters by defining an 
        # additional input variable Xo = 1
        self.w = np.random.uniform(min, max, [M,D+1])

        # vector of input prepended with 1 to handle bias
        self.input = np.zeros(D+1)
        self.input[0] = 1.0

        # output before activation
        self.a = np.zeros(M)

        # set activation function for layer
        self.actFunc = actFunc

    def calcOutput(self, input):
        self.input[1:] = input
        self.a = np.sum(self.w * self.input, axis=1)
        return self.actFunc(self.a)

class Trainer():
    '''
    Trainer for the neural network.
    '''

    def __init__(self, net, Xtrain, Ytrain, errorFunc, **args):
        self._net = net
        self.train = Xtrain
        self.target = Ytrain
        self._errorFunc = errorFunc
        self._err = 0.0
        self._iter = 0
        self._optArgs = {}

        if "show" in args:
            self._show = args["show"]
        else:
            self._show = 0

        # options for the optimization algorithm
        if "maxiter" in args:
            self._optArgs["maxiter"] = args["maxiter"]
        else:
            self._optArgs["maxiter"] = 250

        if "gtol" in args:
            self._optArgs["gtol"] = args["gtol"]

        # keep track of error for plotting
        self.errHistory = []

        # roll out all network weights as initial guess for optimization function
        # **careful** change this vector -> change network weights
        self._w = net.flattenWeightsRef()

    def _objFunc(self, w):
        '''
        The objective function.

        PARAMETERS
        ----------
        w: flattened vector of network weights at a given iteration

        RETURNS
        -------
        err {float}: error according to the error function of all outputs versus targets 
        '''
        # update neural network weights
        self._w[:] = w

        # first run the input data through the neural net
        output = self._net.calcOutput(self.train)

        # now calculate error
        self._err = self._errorFunc(output, self.target)
        return self._err

    def _jacObjFunc(self, w):
        '''
        Calculates the jacobian of the objective function using backpropagation

        PARAMETERS
        ----------
        w: flattened vector of network weights at a given iteration

        RETURNS
        -------
        delta: vector with length equal to the number of weights in the network. 
               Each element is d(E)/d(w_ji) = d(E)/d(a_j) * d(a_j)/d(w_ji)
        '''

        # update network weights
        self._w[:] = w

        jacob = np.zeros(w.size)

        # sum gradients over all input points
        for inPoint, targPoint in zip(self.train, self.target):
            # run the input data through the neural net
            # outPoint {1xK}
            outPoint = self._net.calcOutput(inPoint[np.newaxis,:])

            jInd = w.size
            # calculate delta at the output neurons
            lLayer = self._net.layers[-1]
            delta = self._errorFunc.derivative(outPoint, targPoint)
            delta = delta.T
            for lInd in reversed(range(self._net.N)):
                l = self._net.layers[lInd]
                numW = l.w.size

                # calculate partial error gradients for weights feeding into this layer
                # here input refers to the output of the previous layer (including activation)
                jacob[jInd-numW:jInd] += np.dot(delta, l.input[np.newaxis,:]).flatten()

                # calculate deltas for previous layer
                # (do not include delta for bias, since that isn't backed up)
                if lInd > 0:
                    lPrev = self._net.layers[lInd-1]
                    a = lPrev.a[:,np.newaxis]
                    delta = np.dot(l.w.T[1:,:], delta) * lPrev.actFunc.derivative(a)

                jInd -= numW

        return jacob
                
    def _optCallback(self, w):
        '''
        Called after each iteration of optimization, as _optCallback(w), where w is the current parameter vector.

        PARAMETERS
        ----------
        w: flattened vector of network weights at a given iteration
        '''
        if self._iter % self._show == 0:
            print "Iteration ", self._iter, "; error: ", self._err
    
        self.errHistory.append(self._err)
        self._iter += 1
        
    def trainBFGS(self):
        wstar = fmin_bfgs(self._objFunc, self._w.copy(), fprime = self._jacObjFunc, callback = self._optCallback, **self._optArgs)

        # set the optimal weights
        self._w[:] = wstar

        return self.errHistory