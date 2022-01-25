from datetime import datetime, date
from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_bcrypt import Bcrypt
from flask_login import LoginManager,  login_required, login_user, logout_user, current_user
from models.Models import Problem, User
from models.Models import db
import re
import os
import subprocess
import shutil


# setup the app
app = Flask(__name__)
app.config['DEBUG'] = True
app.config['SECRET_KEY'] = "SuperSecretKey"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'

db.init_app(app)
bcrypt = Bcrypt(app)

# setup the login manager
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'


# create the db structure
with app.app_context():
    db.create_all()


####  setup routes  ####
@app.route('/')
def home():
    return render_template('home.html', user=current_user)


@app.route("/login", methods=["GET", "POST"])
def login():

    # clear the inital flash message
    session.clear()
    if request.method == 'GET':
        next = request.args.get('next')
        return render_template('login.html', next=next)

    # get the form data
    username = request.form['username']
    password = request.form['password']

    remember_me = False
    if 'remember_me' in request.form:
        remember_me = True

    # query the user
    registered_user = User.query.filter_by(username=username).first()

    # check the passwords
    if registered_user is None or bcrypt.check_password_hash(registered_user.password, password) == False:
        flash('Invalid Username/Password')
        return render_template('login.html')

    # login the user
    login_user(registered_user, remember=remember_me)
    print(request)
    print(request.args.get('next'))
    return redirect(request.args.get('next') or url_for('home'))


@app.route('/register', methods=["GET", "POST"])
def register():
    if request.method == 'GET':
        session.clear()
        return render_template('register.html')

    # get the data from our form
    password = request.form['password']
    conf_password = request.form['confirm-password']
    username = request.form['username']
    email = request.form['email']

    # make sure the password match
    if conf_password != password:
        flash("Passwords do not match")
        return render_template('register.html')

    # check if it meets the right complexity
    check_password = password_check(password)

    # generate error messages if it doesnt pass
    if True in check_password.values():
        for k,v in check_password.items():
            if str(v) is "True":
                flash(k)

        return render_template('register.html')

    # hash the password for storage
    pw_hash = bcrypt.generate_password_hash(password)

    # create a user, and check if its unique
    if username  == "admin":
        user = User(username, pw_hash, email, True)
    else :
        user = User(username, pw_hash, email)
    u_unique = user.unique()

    # add the user
    if u_unique == 0:
        db.session.add(user)
        db.session.commit()
        flash("Account Created")
        return redirect(url_for('login'))

    # else error check what the problem is
    elif u_unique == -1:
        flash("Email address already in use.")
        return render_template('register.html')

    elif u_unique == -2:
        flash("Username already in use.")
        return render_template('register.html')

    else:
        flash("Username and Email already in use.")
        return render_template('register.html')


@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('home'))


# allowed_extensions = ['zip']
# def allowed_file(name):
    # return "." in name and name.rsplit(".", 1)[1].lower() in allowed_extensions

def update_userdata():
    id = current_user.get_id()
    submit_date = datetime.now()
    db.session.query(User).filter(User.id==int(id)).update({User.submit_date : submit_date})
    db.session.commit()


@app.route('/submit/', methods=['GET', 'POST'])
def submit():
    if request.method=='POST':
        if current_user.is_authenticated:
            files=request.files.getlist('file[]')  
            savepath = os.path.join('results', str(current_user.id))
            shutil.rmtree(savepath)          
            for file in files:
                pathexist = os.path.exists(savepath)
                if not pathexist:
                    os.makedirs(savepath)
                file.save(os.path.join(savepath, file.filename))

                # update database info for submitdate
            update_userdata()
            flash("Your answer submitted successfully")
            return redirect(url_for('home', user= current_user))
        else:
            flash("You must log in for submit")
            return redirect(url_for('login'))
    else:
        problem = Problem.query.filter_by(isprogressing = True).first()
        return render_template('submit.html', user=current_user, problem=problem)

@app.route('/score/')
@login_required
def score():
    return render_template('score.html', user=current_user)


@app.route('/admin/', methods=['GET', 'POST'])
@login_required
def admin():
    # query the all students
    students = User.query.filter_by(isadmin=False).all()
    if request.method=="GET":
        if current_user.isadmin:
            return render_template('admin.html', students=students, user=current_user)
        else:
            flash("You must be admin")
            return redirect(url_for('login'))
    else:
        content = request.form['problem_content']
        deadline_str = request.form['deadline']
        deadline = datetime. strptime(deadline_str, "%Y/%m/%d %H:%M:%S")
        problem=Problem(content, deadline, True)
        # change all previous problems state Flase
        db.session.query(Problem).filter(Problem.isprogressing==True).update({Problem.isprogressing: False})
        db.session.add(problem)
        print(problem.deadline)
        db.session.commit()
        return render_template("admin.html", problem=problem, students=students, user=current_user)

@app.route('/admin/autograding', methods=['POST'])
def autograding():
    command=str(request.form['command'])
    out_file = command.split(" ")[2]
    problem = Problem.query.filter(Problem.isprogressing==True).first()
    students = User.query.filter(User.isadmin==False).all()
    for student in students:
        resultpath = os.path.join("results", str(student.id))
        arg = "cd "+resultpath+" && "
        p = subprocess.Popen([arg+command],stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, shell=True)
        compile_output, compile_error = p.communicate()
        compile_error = compile_error.decode('utf-8')
        valgrind_error = None
        score = 0
        total_case = 0
        correct_case = 0
        if not compile_error:
            p1 = subprocess.Popen([arg + "valgrind ./"+out_file], stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, shell=True)
            valgrind_output, valgrind_error = p1.communicate()
            subprocess.Popen([arg+"rm "+out_file+".out"], universal_newlines=True, shell=True)
            total_case = len(valgrind_output.split("\n"))
            incorrect_case = compile_output.count(">")
            correct_case = total_case - incorrect_case
            # count delayed data
            delay_hours = 0
            submit_date = student.submit_date
            deadline = problem.deadline
            delay_hours = divmod((submit_date - deadline).total_seconds(), 3600)[0]
            if delay_hours <= 24:
                score = correct_case
            elif delay_hours <= 48:
                score = correct_case - correct_case*0.3
            elif delay_hours <= 72:
                score = correct_case - correct_case*0.5
            elif delay_hours <= 120:
                score = correct_case - correct_case *0.7
            else:
                score = 0
        # update student's data
        db.session.query(User).filter(User.id==student.id).update({User.gcc_message: compile_error, User.valgrind_error:valgrind_error, User.total_case:total_case, User.correct_case: correct_case, User.delay_hours : delay_hours, User.score:score})
        db.session.commit()
    students = User.query.filter(User.isadmin==False).all()
    return redirect(url_for('admin', problem=problem, students=students, user=current_user))



####  end routes  ####

# required function for loading the right user
@login_manager.user_loader
def load_user(id):
    return User.query.get(int(id))

# check password complexity
def password_check(password):
    """
    Verify the strength of 'password'
    Returns a dict indicating the wrong criteria
    A password is considered strong if:
        8 characters length or more
        1 digit or more
        1 symbol or more
        1 uppercase letter or more
        1 lowercase letter or more
        credit to: ePi272314
        https://stackoverflow.com/questions/16709638/checking-the-strength-of-a-password-how-to-check-conditions
    """

    # calculating the length
    length_error = len(password) <= 8

    # searching for digits
    digit_error = re.search(r"\d", password) is None

    # searching for uppercase
    uppercase_error = re.search(r"[A-Z]", password) is None

    # searching for lowercase
    lowercase_error = re.search(r"[a-z]", password) is None

    # searching for symbols
    symbol_error = re.search(r"[ !@#$%&'()*+,-./[\\\]^_`{|}~"+r'"]', password) is None

    ret = {
        'Password is less than 8 characters' : length_error,
        'Password does not contain a number' : digit_error,
        'Password does not contain a uppercase character' : uppercase_error,
        'Password does not contain a lowercase character' : lowercase_error,
        'Password does not contain a special character' : symbol_error,
    }

    return ret



if __name__ == "__main__":
	# change to app.run(host="0.0.0.0"), if you want other machines to be able to reach the webserver.
	app.run() 
