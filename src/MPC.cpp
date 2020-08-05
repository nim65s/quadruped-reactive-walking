#include "example-adder/MPC.hpp"

MPC::MPC(double dt_in, int n_steps_in, double T_gait_in)
{
    std::cout << "START INIT" << std::endl;
    dt = dt_in;
    n_steps = n_steps_in;
    T_gait = T_gait_in;

    xref = Eigen::Matrix<double, 12, Eigen::Dynamic>::Zero(12, 1+n_steps);
    x = Eigen::Matrix<double, 12, Eigen::Dynamic>::Zero(12, 1+n_steps);
    S_gait = Eigen::Matrix<int, Eigen::Dynamic, 1>::Zero(12*n_steps, 1);
    warmxf = Eigen::Matrix<double, Eigen::Dynamic, 1>::Zero(12*n_steps*2, 1);

    // Predefined variables
    mass = 2.50000279f;
    mu = 0.9f;
    cpt_ML = 0;
    cpt_P = 0;

    // Predefined matrices
    gI << 3.09249e-2f, -8.00101e-7f, 1.865287e-5f,
          -8.00101e-7f, 5.106100e-2f, 1.245813e-4f,
          1.865287e-5f, 1.245813e-4f, 6.939757e-2f;
    q << 0.0f, 0.0f, 0.2027682f, 0.0f, 0.0f, 0.0f;
    h_ref = q(2, 0);
    g(8, 0) = -9.81f * dt;
}
 
/*
Create the constraint matrices of the MPC (M.X = N and L.X <= K)
Create the weight matrices P and Q of the MPC solver (cost 1/2 x^T * P * X + X^T * Q)
*/
int MPC::create_matrices()
{
    // Create the constraint matrices
    create_ML();
    create_NK();

    // Create the weight matrices
    create_weight_matrices();

    return 0;
}

/*
Add a new non-zero coefficient to the ML matrix by filling the triplet r_ML / c_ML / v_ML
*/
inline void MPC::add_to_ML(int i, int j, double v)
{
    r_ML[cpt_ML] = i; // row index
    c_ML[cpt_ML] = j; // column index
    v_ML[cpt_ML] = v; // value of coefficient
    cpt_ML++; // increment the counter
}

/*
Add a new non-zero coefficient to the P matrix by filling the triplet r_P / c_P / v_P
*/
inline void MPC::add_to_P(int i, int j, double v)
{
    r_P[cpt_P] = i; // row index
    c_P[cpt_P] = j; // column index
    v_P[cpt_P] = v; // value of coefficient
    cpt_P++; // increment the counter
}

/*
Create the M and L matrices involved in the MPC constraint equations M.X = N and L.X <= K
*/
int MPC::create_ML()
{
    
    std::fill_n(v_ML, size_nz_ML, -1.0); // initialized to -1.0

    // Put identity matrices in M
    for (int k=0; k<(12*n_steps); k++)
    {
        add_to_ML(k, k, -1.0);
    }
    
    // Put A matrices in M
    for (int k=0; k<n_steps-1; k++)
    {   
        for (int i=0; i<12; i++)
        {
            add_to_ML((k+1)*12 + i, (k*12) + i, 1.0);
        }
        for (int i=0; i<6; i++)
        {
            add_to_ML((k+1)*12 + i, (k*12) + i + 6, dt);
        }
    }

    // Put B matrices in M
    double div_tmp = dt / mass;
    for (int k=0; k<n_steps; k++)
    {   
        for (int i=0; i<4; i++)
        {
            add_to_ML(12*k + 6, 12*(n_steps+k) + 0+3*i, div_tmp);
            add_to_ML(12*k + 7, 12*(n_steps+k) + 1+3*i, div_tmp);
            add_to_ML(12*k + 8, 12*(n_steps+k) + 2+3*i, div_tmp);
        }
        for (int i=0; i<12; i++)
        {
            add_to_ML(12*k + 9,  12*(n_steps+k) + i, 8.0);
            add_to_ML(12*k + 10, 12*(n_steps+k) + i, 8.0);
            add_to_ML(12*k + 11, 12*(n_steps+k) + i, 8.0);
        }   
    }
    for (int i=0; i<4; i++)
    {
        B(6, 0+3*i) = div_tmp;
        B(7, 1+3*i) = div_tmp;
        B(8, 2+3*i) = div_tmp;
        B(9,  i) = 8.0;
        B(10, i) = 8.0;
        B(11, i) = 8.0;
    }  

    // Add lines to enable/disable forces
    for (int i=12*n_steps; i<12*n_steps*2; i++)
    {
        for (int j=12*n_steps; j<12*n_steps*2; j++)
        {
            add_to_ML(i, j, 1.0);
        } 
    }

    // Fill ML with F matrices
    int offset_L = 12*n_steps*2;
    for (int k=0; k<n_steps; k++)
    {   
        int di = offset_L+20*k;
        int dj = 12*(n_steps+k);
        // Matrix F with top left corner at (di, dj) in ML
        for (int i=0; i<4; i++)
        {
            int dx = 5*i;
            int dy = 3*i;
            int a [9] = {0, 1, 2, 3, 0, 1, 2, 3, 4};
            int b [9] = {0, 0, 1, 1, 2, 2, 2, 2, 2};
            double c [9] = {1.0, -1.0, 1.0, -1.0, -mu, -mu, -mu, -mu, -1};
            // Matrix C with top left corner at (dx, dy) in F
            for (int j=0; j<9; j++)
            {
                add_to_ML(di+dx+a[j], dj+dy+b[j], c[j]);
            }
        }
    }
    
    // Creation of CSC matrix
    ML = csc_matrix(12*n_steps*2 + 20*n_steps, 12*n_steps*2, size_nz_ML, 
                         v_ML, r_ML, c_ML);

    // Create indices list that will be used to update ML
    int i_x_tmp[12] = {6, 9, 10, 11, 7, 9, 10, 11, 8, 9, 10, 11};
    for (int k=0; k<4; k++)
    {
        for (int i=0; i<12; i++)
        {
            i_x_B[12*k+i] = i_x_tmp[i];
            i_y_B[12*k+i] = (12*k+i) / 4; // 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2...
        }
    }

    int i_start = 30*n_steps-18;
    int i_data [12] = {0, 1, 2, 3, 7, 8, 9, 10, 14, 15, 16, 17};
    int i_foot [4] = {0*24, 1*24, 2*24, 3*24};
    for (int k=0; k<4; k++)
    {
        for (int i=0; i<12; i++)
        {
            i_update_B[12*k+i] = i_start + i_data[i] + i_foot[k];
        }
    }

    // i_update_S here?

    // Update state of B
    for (int k=0; k<n_steps; k++)
    { 
        // Get inverse of the inertia matrix for time step k
        double c = cos(xref(5, k));
        double s = sin(xref(5, k));
        Eigen::Matrix<double, 3, 3> R;
        R << c, -s, 0.0, s, c, 0.0, 0.0, 0.0, 1.0;
        Eigen::Matrix<double, 3, 3> R_gI = R * gI;
        Eigen::Matrix<double, 3, 3> I_inv = R_gI.inverse(); 

        // Get skew-symetric matrix for each foothold
        Eigen::Matrix<double, 3, 4> l_arms = footholds - (xref.block(0, k, 3, 1)).replicate<1,4>();
        for (int i=0; i<4; i++)
        {
            B.block(9, 3*i, 3, 3) = dt * (I_inv * getSkew(l_arms.col(i)));
        }

        int i_iter = 24 * 4 * k;
        for (int j=0; j<12*4; j++)
        {
            ML->x[i_update_B[j] + i_iter] = B(i_x_B[j], i_y_B[j]);
        }
        
    }

    // Update lines to enable/disable forces
    construct_S();
    
    Eigen::Matrix<int, 3, 1> i_tmp1;
    i_tmp1 << 3 + 4, 3 + 4, 6 + 4;
    Eigen::Matrix<int, Eigen::Dynamic, 1> i_tmp2 = Eigen::Matrix<int, Eigen::Dynamic, 1>::Zero(12*n_steps,1);//i_tmp1.replicate<4,1>();
    for (int k=1; k<4*n_steps; k++)
    {
        i_tmp2.block(3*k, 0, 3, 1) = i_tmp1;
    }

    i_off = Eigen::Matrix<int, Eigen::Dynamic, 1>::Zero(12*n_steps,1);
    for (int k=1; k<12*n_steps; k++)
    {
        i_off(k, 0) = i_off(k-1, 0) + i_tmp2(k-1, 0);
        ML->x[i_off(k, 0)+ i_start] = S_gait(k, 0);
    }

    return 0;
}

/*
Create the N and K matrices involved in the MPC constraint equations M.X = N and L.X <= K
*/       
int MPC::create_NK()
{
    // Create NK matrix (upper and lower bounds)
    NK_up = Eigen::Matrix<double, Eigen::Dynamic, 1>::Zero(12*n_steps*2 + 20*n_steps, 1);
    NK_low = Eigen::Matrix<double, Eigen::Dynamic, 1>::Zero(12*n_steps*2 + 20*n_steps, 1);

    // Fill N matrix with g matrices
    for (int k=0; k<n_steps; k++)
    {
        NK_up(12*k+8, 0) = - g(8, 0); // only 8-th coeff is non zero
    }
    
    // Including - A*X0 in the first row of N
    NK_up.block(0, 0, 12, 1) += A * (-x0) ;

    // Create matrix D (third term of N) and put identity matrices in it
    D = Eigen::Matrix<double, Eigen::Dynamic, Eigen::Dynamic>::Identity(12*n_steps, 12*n_steps);

    // Put -A matrices in D
    for (int k=0; k<n_steps-1; k++)
    {   
        for (int i=0; i<12; i++)
        {
            D((k+1)*12 + i, (k*12) + i) = -1.0;
        }
        for (int i=0; i<6; i++)
        {
            D((k+1)*12 + i, (k*12) + i + 6) = -dt;
        }
    }

    // Add third term to matrix N
    Eigen::Map<Eigen::MatrixXd> xref_col((xref.block(0, 1, 12, n_steps)).data(), 12*n_steps, 1);
    NK_up.block(0, 0, 12*n_steps, 1) += D * xref_col;

    // Lines to enable/disable forces are already initialized (0 values)
    // Matrix K is already initialized (0 values)
    Eigen::Matrix<double, Eigen::Dynamic, 1> inf_lower_bount = -std::numeric_limits<double>::infinity() * Eigen::Matrix<double, Eigen::Dynamic, 1>::Ones(20*n_steps, 1);
    for (int k=0; (4+5*k)<(20*n_steps); k++)
    {
        inf_lower_bount(4+5*k, 0) = - 25.0;
    }

    NK_low.block(0, 0, 12*n_steps*2, 1) = NK_up.block(0, 0, 12*n_steps*2, 1);
    NK_low.block(12*n_steps*2, 0, 20*n_steps, 1) = inf_lower_bount;

    // Convert to c_double arrays
    /*std::vector<c_double> vec_up(NK_up.data(), NK_up.data() + NK_up.size());
    std::copy(vec_up.begin(), vec_up.end(), v_NK_up);
    std::vector<c_double> vec_low(NK_low.data(), NK_low.data() + NK_low.size());
    std::copy(vec_low.begin(), vec_low.end(), v_NK_low);*/

    Eigen::Matrix<double, Eigen::Dynamic, 1>::Map(&v_NK_up[0], NK_up.size()) = NK_up;
    Eigen::Matrix<double, Eigen::Dynamic, 1>::Map(&v_NK_low[0], NK_low.size()) = NK_low;

    return 0;
}


/*
Create the weight matrices P and q in the cost function x^T.P.x + x^T.q of the QP problem
*/
int MPC::create_weight_matrices()
{
    // Number of states
    // int n_x = 12;

    // Define weights for the x-x_ref components of the optimization vector   
    // Hand-tuning of parameters if you want to give more weight to specific components
    double w [12] = {0.5f, 0.5f, 2.0f, 0.11f, 0.11f, 0.11f};
    w[6] = 2.0f*sqrt(w[0]);
    w[7] = 2.0f*sqrt(w[1]);
    w[8] = 2.0f*sqrt(w[2]);
    w[9] = 0.05f*sqrt(w[3]);
    w[10] = 0.05f*sqrt(w[4]);
    w[11] = 0.05f*sqrt(w[5]);
    for (int k=0; k<n_steps; k++)
    {
        for (int i=0; i<12; i++)
        {
             add_to_P(12*k + i, 12*k + i, w[i]);
        } 
    }
    
    // Define weights for the force components of the optimization vector
    for (int k=n_steps; k<(2*n_steps); k++)
    {
        for (int i=0; i<12; i++)
        {
            add_to_P(12*k + 0, 12*k + 0, 1e-4f);
            add_to_P(12*k + 1, 12*k + 1, 1e-4f);
            add_to_P(12*k + 2, 12*k + 2, 1e-4f);
        } 
    }

    // Creation of CSC matrix
    P = csc_matrix(12*n_steps*2, 12*n_steps*2, size_nz_P, v_P, r_P, c_P);

    // Q is already created filled with zeros

    return 0;
}

/*
Update the M, N, L and K constraint matrices depending on what happened
*/
int MPC::update_matrices(Eigen::Matrix<double, 20, 13> fsteps)
{

    /* M need to be updated between each iteration:
     - lever_arms changes since the robot moves
     - I_inv changes if the reference velocity vector is modified
     - footholds need to be enabled/disabled depending on the contact sequence */
    update_ML(fsteps);

    /* N need to be updated between each iteration:
     - X0 changes since the robot moves
     - Xk* changes since X0 is not the same */
    update_NK();

    // L matrix is constant
    // K matrix is constant

    return 0;
}

/*
Update the M and L constaint matrices depending on the current state of the gait

*/
int MPC::update_ML(Eigen::Matrix<double, 20, 13> fsteps)
{

    int j = 0;
    int k_cum = 0;
    // Iterate over all phases of the gait
    while (gait(j, 0) != 0)
    {
        for (int k=k_cum; k<(k_cum+gait(j, 0)); k++)
        {
            // Get inverse of the inertia matrix for time step k
            double c = cos(xref(5, k));
            double s = sin(xref(5, k));
            Eigen::Matrix<double, 3, 3> R;
            R << c, -s, 0.0, s, c, 0.0, 0.0, 0.0, 1.0;
            Eigen::Matrix<double, 3, 3> R_gI = R * gI;
            Eigen::Matrix<double, 3, 3> I_inv = R_gI.inverse(); 

            // Get skew-symetric matrix for each foothold
            Eigen::Map<Eigen::MatrixXd> fsteps_tmp((fsteps.block(j, 1, 1, 12)).data(), 3, 4);
            lever_arms = fsteps_tmp - (xref.block(0, k, 3, 1)).replicate<1,4>();
            for (int i=0; i<4; i++)
            {
                B.block(9, 3*i, 3, 3) = dt * (I_inv * getSkew(lever_arms.col(i)));
            }

            // Replace the coefficient directly in ML.data
            int i_iter = 24 * 4 * k;
            for (int i=0; i<12*4; i++)
            {
                ML->x[i_update_B[i] + i_iter] = B(i_x_B[i], i_y_B[i]);
            }
        }

        k_cum += gait(j, 0);
        j++;
    }

    // Construct the activation/desactivation matrix based on the current gait
    construct_S();

    // Update lines to enable/disable forces
    int i_start = 30*n_steps-18;
    for (int k=1; k<12*n_steps; k++)
    {
        ML->x[i_off(k, 0)+ i_start] = S_gait(k, 0);
    }

    return 0;
}

/*
Update the N and K matrices involved in the MPC constraint equations M.X = N and L.X <= K
*/
int MPC::update_NK()
{
    // Matrix g is already created and not changed
    // Fill N matrix with g matrices
    for (int k=0; k<n_steps; k++)
    {
        NK_up(12*k+8, 0) = - g(8, 0); // only 8-th coeff is non zero
    }

    // Including - A*X0 in the first row of N
    NK_up.block(0, 0, 12, 1) += A * (-x0);

    // Matrix D is already created and not changed
    // Add third term to matrix N
    Eigen::Map<Eigen::MatrixXd> xref_col((xref.block(0, 1, 12, n_steps)).data(), 12*n_steps, 1);
    NK_up.block(0, 0, 12*n_steps, 1) += D * xref_col;
    
    // Update upper bound c_double array (unrequired since Map is just pointers?)
    Eigen::Matrix<double, Eigen::Dynamic, 1>::Map(&v_NK_up[0], NK_up.size()) = NK_up;

    // Update lower bound c_double array
    NK_low.block(0, 0, 12*n_steps*2, 1) = NK_up.block(0, 0, 12*n_steps*2, 1);
    Eigen::Matrix<double, Eigen::Dynamic, 1>::Map(&v_NK_low[0], NK_low.size()) = NK_low;

    return 0;
}

/*
Create an initial guess and call the solver to solve the QP problem
*/
int MPC::call_solver(int k)
{
    // Initial guess for forces (mass evenly supported by all legs in contact)
    warmxf.block(0, 0, 12*(n_steps-1), 1) = x.block(12, 0, 12*(n_steps-1), 1);
    warmxf.block(12*n_steps, 0, 12*(n_steps-1), 1) = x.block(12*(n_steps+1), 0, 12*(n_steps-1), 1);
    warmxf.block(12*(2*n_steps-1), 0, 12, 1) = x.block(12*n_steps, 0, 12, 1);

    // Setup the solver (first iteration) then just update it
    if (k == 0)  // Setup the solver with the matrices
    {
        data->n = 12*n_steps*2; // number of variables
        data->m = 12*n_steps*2 + 20*n_steps; // number of constraints
        data->P = P;  // the upper triangular part of the quadratic cost matrix P in csc format (size n x n)
        data->A = ML;  // linear constraints matrix A in csc format (size m x n) 
        data->q = &Q[0]; // dense array for linear part of cost function (size n) 
        data->l = &v_NK_low[0];  // dense array for lower bound (size m)  
        data->u = &v_NK_up[0];  // dense array for upper bound (size m) 
        
        osqp_setup( &workspce, data, settings);
        osqp_solve(workspce);

        /*self.prob.setup(P=self.P, q=self.Q, A=self.ML, l=self.NK_inf, u=self.NK.ravel(), verbose=False)
        self.prob.update_settings(eps_abs=1e-5)
        self.prob.update_settings(eps_rel=1e-5)*/
    }
    else  // Code to update the QP problem without creating it again
    {
        /*
        self.prob.update(Ax=self.ML.data, l=self.NK_inf, u=self.NK.ravel())
        self.prob.warm_start(x=self.warmxf) 
        */
    }
    
    // Run the solver to solve the QP problem
    //osqp_solve(workspce);
    /*self.sol = self.prob.solve()
    self.x = self.sol.x*/
    // solution in workspce->solution->x

    return 0;
}

/*
Extract relevant information from the output of the QP solver
*/
int MPC::retrieve_result()
{
    // Retrieve the "contact forces" part of the solution of the QP problem
    for (int k=0; k<12; k++)
    {
        f_applied[k] = (workspce->solution->x)[12*n_steps+k];
    }

    return 0;
}

/*
Return the latest desired contact forces that have been computed
*/
double * MPC::get_latest_result()
{
    return &f_applied[0];
}

/*
Run one iteration of the whole MPC by calling all the necessary functions (data retrieval,
update of constraint matrices, update of the solver, running the solver, retrieving result)
*/
int MPC::run(Eigen::Matrix<double, 12, Eigen::Dynamic> xref_in, Eigen::Matrix<double, 20, 13> fsteps_in)
{
    // Recontruct the gait based on the computed footsteps
    construct_gait(fsteps_in);

    // Retrieve data required for the MPC
    xref = xref_in;
    x0 = xref_in.block(0, 0, 12, 1);

    return 0;
}

/*
Returns the skew matrix of a 3 by 1 column vector
*/
Eigen::Matrix<double, 3, 3> MPC::getSkew(Eigen::Matrix<double, 3, 1> v)
{
    Eigen::Matrix<double, 3, 3> result;
    result << 0.0, -v(2, 0), v(1, 0), v(2, 0), 0.0, -v(0, 0), -v(1, 0), v(0, 0), 0.0;
    return result;
}

/*
Construct an array of size 12*N that contains information about the contact state of feet.
This matrix is used to enable/disable contact forces in the QP problem.
N is the number of time step in the prediction horizon.
*/
int MPC::construct_S()
{
    int i = 0;
    int k = 0;

    Eigen::Matrix<int, 20, 5> inv_gait = Eigen::Matrix<int, 20, 5>::Ones() - gait;
    while (gait(i, 0) != 0)
    {
        // S_gait.block(k*12, 0, gait[i, 0]*12, 1) = (1 - (gait.block(i, 1, 1, 4)).transpose()).replicate<gait[i, 0], 1>() not finished;
        for (int a=0; a<gait(i, 0); a++)
        {
            for (int b=0; b<4; b++)
            {
                for (int c=0; c<3; c++)
                {
                    S_gait(k*12, gait(i, 0)*12 + 12*a + 4*b + c) = inv_gait(i, 1+b);
                }
            }
        }
        k += gait(i, 0);
        i++;
    }

    return 0;
}

/*
Reconstruct the gait matrix based on the fsteps matrix since only the last one is received by the MPC
*/
int MPC::construct_gait(Eigen::Matrix<double, 20, 13> fsteps_in)
{
    // First column is identical
    gait.col(0) = fsteps_in.col(0).cast <int> ();

    int k = 0;
    while (gait(k, 0) != 0)
    {
        for (int i=0; i<4; i++)
        {
            if (fsteps_in(k, 1+i*3) == 0.0)
            {
                gait(k, 1+i) = 0;
            }
            else
            {
                gait(k, 1+i) = 1;
            }
        }
        k++;
    }
    return 0;
}
